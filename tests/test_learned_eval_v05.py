"""No private training data or global NumPy needed at runtime."""
import json
import chess
import pytest
from engine.learned_eval import DIM, LinearEvaluator, feature_vector
from engine.search import Engine


def model():
    return {'schema': 1, 'architecture': 'symmetric_linear_pst_v1',
            'version': 'test', 'weights_cp': [0.0] * DIM}


def test_learned_evaluation_material_and_symmetry():
    e=LinearEvaluator(model())
    b=chess.Board('4k3/8/8/8/8/8/4Q3/4K3 w - - 0 1')
    assert e.evaluate(b)==900
    assert e.evaluate(b.mirror())==900   # Side to move reversed as well.
    assert feature_vector(b)[1]==900
    b.turn=chess.BLACK
    assert e.evaluate(b)==-900


def test_model_is_a_real_generalizer_not_lookup():
    raw=model()
    raw['weights_cp'][(chess.KNIGHT-1)*64+chess.F3]=85
    e=LinearEvaluator(raw)
    a=chess.Board(); a.push_san('Nf3')
    other=chess.Board(); other.push_san('e4'); other.push_san('e5'); other.push_san('Nf3')
    zero=LinearEvaluator(model())
    assert e.evaluate(a) != zero.evaluate(a)
    assert e.evaluate(other) != zero.evaluate(other)


def test_reject_bad_weights():
    raw=model(); raw['weights_cp'][0]=float('nan')
    with pytest.raises(ValueError): LinearEvaluator(raw)
    raw=model(); raw['weights_cp']=[]
    with pytest.raises(ValueError): LinearEvaluator(raw)


def test_engine_learner_is_optional_and_reloaded(tmp_path):
    path=tmp_path/'evaluator.json';path.write_text(json.dumps(model()))
    e=Engine(learned_eval_path=path)
    b=chess.Board('4k3/8/8/8/8/8/4Q3/4K3 w - - 0 1')
    assert not e.learned_eval_enabled
    e.learned_eval_enabled=True
    assert e.evaluation(b)==900
    e.new_game()
    assert e._learned_evaluator is None