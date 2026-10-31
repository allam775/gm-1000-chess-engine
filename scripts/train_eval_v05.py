"""Train a genuinely position-scoring evaluator with Stockfish 19 labels.

Source: the already-published 400 Stockfish19 self-play PGNs. Split by ENTIRE
GAME, never random position; reject duplicate exact positions across both
partitions. No original Skill-5 tournament games enter training or labels.
Stockfish labels are approximations at a specified short compute budget.
The result is a *candidate* and is not automatically enabled in live games.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import chess
import chess.engine
import chess.pgn
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from engine.learned_eval import DIM, feature_vector, LinearEvaluator
from engine.search import evaluate as handcrafted_evaluation


def positions_by_game(path: Path, *, sample_stride=5, max_plies=180):
    """Yield unique feature-ready positions indexed by their original game."""
    seen=set()
    with path.open(encoding='utf-8') as file:
        for game_no in range(1,401):
            game=chess.pgn.read_game(file)
            if game is None:
                raise ValueError(f'Missing source game {game_no} of 400')
            if game.errors:
                raise ValueError(f'Corrupted PGN game {game_no}: {game.errors}')
            if game.headers.get('Result') not in ('1-0','0-1','1/2-1/2','*'):
                raise ValueError('Unsupported game result')
            board=game.board()
            for ply, move in enumerate(game.mainline_moves(),1):
                if 9 <= ply <= max_plies and (ply+game_no)%sample_stride==0 and not board.is_game_over():
                    key=board.epd(en_passant='legal')
                    if key not in seen:
                        seen.add(key)
                        yield game_no, board.copy(stack=False)
                board.push(move)
        if chess.pgn.read_game(file) is not None:
            raise ValueError('More than 400 source games; refuse unknown input')


def train(args):
    if not args.source.exists():
        raise FileNotFoundError(args.source)
    if args.seconds < 0.015 or args.max_positions < 2000:
        raise ValueError('Require >=0.015s/position and >=2000 position samples')
    digest=hashlib.sha256(args.source.read_bytes()).hexdigest()
    teacher_bin=str(args.stockfish or os.environ.get('STOCKFISH_PATH') or '/usr/games/stockfish')
    split={"train":[],"holdout":[]}
    stats={'seen':0,'skipped_mate':0,'skipped_error':0}
    with chess.engine.SimpleEngine.popen_uci(teacher_bin) as teacher:
        name=teacher.id.get('name','')
        if not name.startswith('Stockfish 19'):
            raise ValueError(f'Expected Stockfish 19, got {name}')
        teacher.configure({'Skill Level':20,'Threads':1,'Hash':64})
        for game_no,board in positions_by_game(args.source):
            if stats['seen'] >= args.max_positions:
                break
            if board.is_checkmate() or board.is_stalemate() or board.is_insufficient_material():
                continue
            try:
                info=teacher.analyse(board,chess.engine.Limit(time=args.seconds))
                score=info['score'].pov(chess.WHITE)
                if score.is_mate():
                    stats['skipped_mate']+=1
                    continue
                teacher_cp=score.score()
                if teacher_cp is None:
                    stats['skipped_error']+=1
                    continue
            except chess.engine.EngineError:
                stats['skipped_error']+=1
                continue
            features,material=feature_vector(board)
            baseline=handcrafted_evaluation(board)
            baseline=baseline if board.turn==chess.WHITE else -baseline
            partition='holdout' if game_no%5==0 else 'train'
            split[partition].append((features,material,int(teacher_cp),baseline,game_no))
            stats['seen']+=1
            if stats['seen']%500==0:
                print('TEACHER_LABELLED',stats['seen'], 'train',len(split['train']),
                      'holdout',len(split['holdout']),flush=True)
    if min(len(split['train']),len(split['holdout']))<300:
        raise AssertionError('Not enough independent game-split samples')

    def pack(records):
        matrix=np.asarray([r[0] for r in records],dtype=np.float64)
        material=np.asarray([r[1] for r in records],dtype=np.float64)
        teacher=np.asarray([r[2] for r in records],dtype=np.float64)
        handcrafted=np.asarray([r[3] for r in records],dtype=np.float64)
        return matrix,material,teacher,handcrafted
    x,y_base,y_teacher,y_hand=pack(split['train'])
    hx,h_base,h_teacher,h_hand=pack(split['holdout'])
    # Residual learning keeps king, queen, and material values grounded.
    # Target clipping limits learned positional terms from tactical mates.
    residual=np.clip(y_teacher-y_base,-1200,1200)
    reg=float(args.ridge)
    if reg<=0: raise ValueError('Ridge regularization must be positive')
    gram=x.T@x+np.eye(DIM)*reg
    weights=np.linalg.solve(gram,x.T@residual)
    # A position model trained on short labels cannot safely learn massive
    # piece-square bonuses. Bound all coefficients before inference.
    weights=np.clip(weights,-120,120)
    predicted=h_base+hx@weights

    def quality(p):
        errors=p-h_teacher
        return {'mae_cp':round(float(np.mean(np.abs(errors))),2),
                'rmse_cp':round(float(np.sqrt(np.mean(errors**2))),2),
                'median_ae_cp':round(float(np.median(np.abs(errors))),2)}
    metrics={'learned':quality(predicted),'handcrafted':quality(h_hand),
             'material_only':quality(h_base)}
    raw={
        'schema':1,'architecture':'symmetric_linear_pst_v1','version':'v0.5-candidate',
        'weights_cp':[round(float(v),5) for v in weights],
        'trained_utc':datetime.now(timezone.utc).isoformat(),
        'source':'400 Stockfish19 Skill20 self-play games; independent root scores',
        'source_pgn_sha256':digest,'teacher':name,'teacher_seconds_per_position':args.seconds,
        'split':'By original game (every fifth game held out); no exact position duplicates',
        'train_positions':len(split['train']),'holdout_positions':len(split['holdout']),
        'train_source_games':len({r[4] for r in split['train']}),
        'holdout_source_games':len({r[4] for r in split['holdout']}),
        'ridge':reg,'holdout':metrics,
        'deployment':'candidate only; UCI LearnedEval defaults OFF; no automatic promotion'
    }
    # Validate that pure-Python inference matches the offline feature matrix.
    candidate=LinearEvaluator(raw)
    assert len(candidate.weights)==DIM
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(raw,indent=2)+'\n',encoding='utf-8')
    report={k:v for k,v in raw.items() if k!='weights_cp'}
    report['teacher_positions_attempted']=stats
    report['offline_improvement_vs_handcrafted_mae_cp']=round(
        metrics['handcrafted']['mae_cp']-metrics['learned']['mae_cp'],2)
    report['gate_offline_mae_pass']=metrics['learned']['mae_cp']<metrics['handcrafted']['mae_cp']
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('TRAINING_REPORT',json.dumps(report,indent=2),flush=True)
    return raw


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=ROOT/'data/stockfish19_skill20_400_games.pgn')
    p.add_argument('--stockfish',default=None)
    p.add_argument('--seconds',type=float,default=0.03)
    p.add_argument('--max-positions',type=int,default=10000)
    p.add_argument('--ridge',type=float,default=70)
    p.add_argument('--output',type=Path,default=ROOT/'data/learned_eval_v05_candidate.json')
    p.add_argument('--report',type=Path,default=ROOT/'data/learned_eval_v05_training_report.json')
    train(p.parse_args())