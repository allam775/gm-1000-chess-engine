/* GM-1000 v0.8 experimental threat-aware native search (independent implementation).
 * Rule generation: pinned MIT Disservin/chess-library, NOT Stockfish search.
 * This engine intentionally has no historical move memories: isolates search.
 */
#include "chess.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

using namespace chess;
namespace {
constexpr int MATE = 30000;
constexpr int INF = 32000;
constexpr int VALUE[7] = {100, 320, 335, 500, 900, 0, 0};
std::mutex output_lock;

void output(const std::string& s) {
    const std::lock_guard<std::mutex> g(output_lock);
    std::cout << s << '\n' << std::flush;
}
int evaluate(const Board& b) {
    // GM-1000's own fast material + positional approximation, not Stockfish eval.
    int scores[2] = {0, 0};
    int bishops[2] = {0, 0};
    int pawns[2][8] = {{0}};
    bool queens_present = b.pieces(PieceType::QUEEN).count() != 0;
    for (int c = 0; c != 2; ++c) {
        const auto color = c ? Color::BLACK : Color::WHITE;
        for (int kind = 0; kind != 6; ++kind) {
            auto bb = b.pieces(PieceType(static_cast<PieceType::underlying>(kind)), color);
            if (kind == 2) bishops[c] = bb.count();
            while (bb) {
                int sq = bb.pop();
                int file = sq & 7;
                int rank = c ? 7 - (sq >> 3) : (sq >> 3);
                int central_file = 3 - std::min(std::abs(file - 3), std::abs(file - 4));
                int central_rank = 3 - std::min(std::abs(rank - 3), std::abs(rank - 4));
                scores[c] += VALUE[kind];
                switch (kind) {
                    case 0: // pawns
                        ++pawns[c][file];
                        scores[c] += 7 * rank + 3 * central_file;
                        break;
                    case 1: scores[c] += 9 * (central_file + central_rank) - (rank == 0 ? 9 : 0); break;
                    case 2: scores[c] += 5 * (central_file + central_rank) - (rank == 0 ? 7 : 0); break;
                    case 3: scores[c] += 2 * rank; break;
                    case 4: scores[c] += 2 * (central_file + central_rank); break;
                    case 5:
                        if (queens_present) {
                            scores[c] += rank <= 1 ? 12 : -8 * rank;
                            if (rank == 0 && (file == 2 || file == 6)) scores[c] += 18;
                        } else { scores[c] += 5 * (central_file + central_rank); }
                        break;
                }
            }
        }
        if (bishops[c] >= 2) scores[c] += 25;
        for (int file = 0; file < 8; ++file) {
            if (pawns[c][file] > 1) scores[c] -= 14 * (pawns[c][file] - 1);
            if (pawns[c][file] && (!file || !pawns[c][file - 1]) &&
                (file == 7 || !pawns[c][file + 1])) scores[c] -= 12 * pawns[c][file];
        }
    }
    // A king with its surrounding flight squares controlled by enemy pieces
    // needs defensive resources. Apply only while major pieces are around.
    for (int c=0; c<2; ++c) {
        const auto color = c ? Color::BLACK : Color::WHITE;
        const auto enemy = ~color;
        if (b.pieces(PieceType::QUEEN, enemy).count()==0 &&
            b.pieces(PieceType::ROOK, enemy).count()<2) continue;
        auto ring = attacks::king(b.kingSq(color));
        int threats=0;
        while (ring) {
            auto sq = Square(static_cast<Square::underlying>(ring.pop()));
            if (b.isAttacked(sq, enemy)) ++threats;
        }
        scores[c] -= 18 * std::min(threats, 5);
    }
    const int white_score = scores[0] - scores[1];
    return b.sideToMove() == Color::WHITE ? white_score : -white_score;
}

bool is_draw(const Board& board) {
    return board.isInsufficientMaterial() || board.isHalfMoveDraw() ||
           (board.halfMoveClock() >= 8 && board.isRepetition(2));
}

struct Entry {
    uint64_t key = 0;
    int32_t score = 0;
    int16_t depth = -1;
    uint8_t flag = 0;  // 0 exact, 1 lower bound, 2 upper bound
    Move move{};
};
struct Aborted {};
struct Result {
    Move move{};
    int depth = 0;
    int score = 0;
    uint64_t nodes = 0;
    double seconds = 0.0;
};

struct Search {
    std::vector<Entry> tt;
    std::array<std::array<Move, 2>, 128> killers{};
    std::array<std::array<int, 64>, 64> history{};
    std::atomic<bool>& stop;
    std::chrono::steady_clock::time_point deadline{};
    bool timed = false;
    uint64_t nodes = 0;
    bool interrupted = false;
    bool null_verification = false;

    explicit Search(std::atomic<bool>& s, size_t tt_entries=1 << 18) :
        tt(tt_entries), stop(s) {}

    bool check_stop() const {
        return stop.load(std::memory_order_relaxed) ||
               (timed && std::chrono::steady_clock::now() >= deadline);
    }
    void node() {
        ++nodes;
        if ((nodes & 255u) == 0 && check_stop()) throw Aborted{};
    }
    int priority(const Board& b, Move m, Move hashmove, int ply) const {
        if (m == hashmove && m.move() != Move::NO_MOVE) return 2000000;
        if (m.typeOf() == Move::PROMOTION) return 1000000 + VALUE[static_cast<int>(m.promotionType().internal())];
        if (b.isCapture(m)) {
            auto victim = b.getCapturing<PieceType>(m);
            auto attacker = b.at<PieceType>(m.from());
            return 100000 + 16 * VALUE[static_cast<int>(victim.internal())] - VALUE[static_cast<int>(attacker.internal())];
        }
        if (ply < 128) {
            if (m == killers[ply][0]) return 95000;
            if (m == killers[ply][1]) return 90000;
        }
        return history[m.from().index()][m.to().index()];
    }
    void order(Movelist& moves, const Board& b, Move hashmove, int ply) const {
        for (auto& m : moves) {
            auto n = priority(b, m, hashmove, ply);
            m.setScore(static_cast<int16_t>(std::max(-32000, std::min(32000, n / 64))));
        }
        std::sort(moves.begin(), moves.end(), [](Move a, Move b) { return a.score() > b.score(); });
    }
    int static_evasion(const Board& b, Movelist& moves, int ply) {
        int best = -INF;
        // At emergency quiescence horizon, never use illegal stand pat in check.
        for (auto m : moves) {
            Board c = b;  // Very rare emergency branch; avoid deep checked recursion.
            c.makeMove(m);
            int v = -evaluate(c);
            if (movegen::anylegalmoves(c) == false && c.inCheck()) v = MATE - ply - 1;
            best = std::max(best, v);
        }
        return best;
    }
    int quiescence(Board& b, int alpha, int beta, int ply, int qdepth) {
        node();
        const bool checked = b.inCheck();
        Movelist moves;
        // Do not generate and score all quiet moves on the vast majority of
        // quiescence nodes. Preserve all legal evasions while checked.
        if (checked) {
            movegen::legalmoves(moves, b);
            if (moves.empty()) return -MATE + ply;
        } else {
            movegen::legalmoves<movegen::MoveGenType::CAPTURE>(moves, b);
            // The captures-only generator omits non-capturing promotions.
            auto pawns = b.pieces(PieceType::PAWN, b.sideToMove());
            const Rank prepromotion = b.sideToMove() == Color::WHITE ? Rank::RANK_7 : Rank::RANK_2;
            if (static_cast<bool>(pawns & Bitboard(prepromotion))) {
                Movelist pushes;
                movegen::legalmoves<movegen::MoveGenType::QUIET>(pushes, b, PieceGenType::PAWN);
                for (auto pm : pushes) if (pm.typeOf()==Move::PROMOTION) moves.add(pm);
            }
            // Stalemate is a draw even if the static evaluation is nonzero.
            if (moves.empty() && !movegen::anylegalmoves(b)) return 0;
        }
        if (is_draw(b)) return 0;
        if (!checked) {
            int stand = evaluate(b);
            if (stand >= beta) return beta;
            alpha = std::max(alpha, stand);
            if (qdepth >= 10) return alpha;
        } else if (qdepth >= 16) {
            return static_evasion(b, moves, ply);
        }
        // Search a bounded number of quiet checking moves at the initial
        // tactical horizon.  The previous engine only searched captures and
        // promotions, which missed forcing checks and defensive necessities.
        // Prevent checking-move explosions by limiting this to qdepth zero.
        if (!checked && qdepth == 0 && ply < 40 &&
            b.hasNonPawnMaterial(b.sideToMove())) {
            Movelist checks;
            movegen::legalmoves<movegen::MoveGenType::QUIET>(checks, b);
            int added = 0;
            for (Move m : checks) {
                if (m.typeOf() == Move::PROMOTION) continue; // already included
                if (b.givesCheck(m) == CheckType::NO_CHECK) continue;
                moves.add(m);
                if (++added == 3) break;
            }
        }
        order(moves, b, Move{}, ply);
        for (Move m : moves) {
            if (!checked && !b.isCapture(m) && m.typeOf() != Move::PROMOTION &&
                !(qdepth == 0 && b.givesCheck(m) != CheckType::NO_CHECK)) continue;
            b.makeMove(m);
            int score;
            try { score = -quiescence(b, -beta, -alpha, ply+1, qdepth+1); }
            catch (...) { b.unmakeMove(m); throw; }
            b.unmakeMove(m);
            if (score >= beta) return beta;
            alpha = std::max(alpha, score);
        }
        return alpha;
    }
    int negamax(Board& b, int depth, int alpha, int beta, int ply) {
        node();
        if (ply >= 120) return evaluate(b);
        const bool checked = b.inCheck();
        if (is_draw(b)) {
            // Checkmate takes priority over 50-move claim at a zero-move node.
            if (checked && !movegen::anylegalmoves(b)) return -MATE + ply;
            return 0;
        }
        if (depth <= 0) return quiescence(b, alpha, beta, ply, 0);
        // Verified, guarded null-move cutoff: when the side already has
        // something better than beta without making any move, searching all
        // ordinary moves is usually unnecessary. Forbid in-check and
        // pawn-only endings (zugzwang), and never trust mate-range bounds.
        if (!null_verification && depth >= 3 && ply >= 1 && !checked &&
            b.hasNonPawnMaterial(b.sideToMove()) &&
            beta < MATE - 512 && alpha > -MATE + 512) {
            b.makeNullMove();
            int null_score;
            try { null_score = -negamax(b, depth - 3, -beta, -beta + 1, ply + 1); }
            catch (...) { b.unmakeNullMove(); throw; }
            b.unmakeNullMove();
            if (null_score >= beta) {
                if (depth <= 4) return beta;
                // A null pass can overlook only-move defenses. Confirm a
                // depth-reduced ordinary search, without recursive null moves.
                null_verification = true;
                int verify;
                try { verify = negamax(b, depth-3, beta-1, beta, ply); }
                catch (...) { null_verification = false; throw; }
                null_verification = false;
                if (verify >= beta) return beta;
            }
        }
        const int old_alpha = alpha;
        auto& entry = tt[b.hash() & (tt.size()-1)];
        Move hashmove{};
        if (entry.key == b.hash()) {
            hashmove = entry.move;
            if (entry.depth >= depth && std::abs(entry.score) < MATE - 200) {
                if (entry.flag == 0) return entry.score;
                if (entry.flag == 1) alpha = std::max(alpha, static_cast<int>(entry.score));
                if (entry.flag == 2) beta = std::min(beta, static_cast<int>(entry.score));
                if (alpha >= beta) return entry.score;
            }
        }
        const int original_beta = beta;
        Movelist moves;
        movegen::legalmoves(moves, b);
        if (moves.empty()) return checked ? -MATE + ply : 0;
        order(moves, b, hashmove, ply);
        int best = -INF;
        Move selected{};
        int searched_moves = 0;
        for (Move m : moves) {
            const bool quiet = !b.isCapture(m) && m.typeOf()!=Move::PROMOTION;
            b.makeMove(m);
            int score;
            try {
                // Late-move reduction with mandatory full-depth verification
                // whenever a reduced quiet move threatens to raise alpha.
                const bool reduce = depth>=5 && searched_moves>=5 &&
                    !checked && quiet && !b.inCheck() &&
                    alpha > -MATE+512 && beta < MATE-512;
                if (reduce) {
                    score = -negamax(b, depth-2, -alpha-1, -alpha, ply+1);
                    if (score>alpha) score = -negamax(b, depth-1, -beta, -alpha, ply+1);
                } else score = -negamax(b, depth-1, -beta, -alpha, ply+1);
            } catch (...) { b.unmakeMove(m); throw; }
            b.unmakeMove(m);
            ++searched_moves;
            if (score > best) { best = score; selected = m; }
            alpha = std::max(alpha, score);
            if (alpha >= beta) {
                if (!b.isCapture(m) && ply < 128) {
                    if (killers[ply][0] != m) {
                        killers[ply][1] = killers[ply][0];
                        killers[ply][0] = m;
                    }
                    int& h = history[m.from().index()][m.to().index()];
                    h = std::min(31000, h + depth*depth);
                }
                break;
            }
        }
        // Only completed subtrees reach here; interruptions never poison TT.
        if (depth >= entry.depth || entry.key != b.hash()) {
            entry.key = b.hash(); entry.score = best; entry.depth = depth;
            entry.move = selected;
            entry.flag = best <= old_alpha ? 2 : (best >= original_beta ? 1 : 0);
        }
        return best;
    }
    Result run(Board position, int max_depth, int millis,
               const std::function<void(const Result&)>& report = {}) {
        nodes = 0;
        timed = millis > 0;
        if (timed) deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(millis);
        const auto start = std::chrono::steady_clock::now();
        Result completed{};
        Movelist legal;
        movegen::legalmoves(legal, position);
        if (legal.empty()) return completed;
        // Cheap legal fallback, rather than the first pseudolegal move.
        int fallback_score = -INF;
        for (Move m : legal) {
            position.makeMove(m);
            int score = -evaluate(position);
            position.unmakeMove(m);
            if (score > fallback_score) { fallback_score = score; completed.move = m; }
        }
        completed.score = fallback_score;
        for (int depth = 1; depth <= std::min(64, max_depth); ++depth) {
            if (check_stop()) break;
            const auto& root_tt = tt[position.hash() & (tt.size()-1)];
            order(legal, position, root_tt.key == position.hash() ? root_tt.move : completed.move, 0);
            int best = -INF;
            int alpha = -INF;
            Move chosen{};
            try {
                for (Move m : legal) {
                    position.makeMove(m);
                    int score;
                    try { score = -negamax(position, depth-1, -INF, -alpha, 1); }
                    catch (...) { position.unmakeMove(m); throw; }
                    position.unmakeMove(m);
                    if (score > best) { best = score; chosen = m; }
                    alpha = std::max(alpha, score);
                }
            } catch (const Aborted&) { interrupted = true; break; }
            if (chosen.move() == Move::NO_MOVE) break;
            completed.move = chosen; completed.score = best; completed.depth = depth;
            completed.nodes = nodes;
            completed.seconds = std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
            if (report) report(completed);
            auto &entry = tt[position.hash() & (tt.size()-1)];
            entry.key = position.hash(); entry.move = chosen; entry.depth = depth;
            entry.score = best; entry.flag = 0;
            if (std::abs(best) > MATE - 150) break;
        }
        completed.nodes = nodes;
        completed.seconds = std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
        return completed;
    }
};

std::uint64_t perft(Board& b, int depth) {
    if (depth == 0) return 1;
    Movelist moves; movegen::legalmoves(moves,b);
    if (depth == 1) return moves.size();
    std::uint64_t count = 0;
    for (Move m : moves) {
        b.makeMove(m); count += perft(b,depth-1); b.unmakeMove(m);
    }
    return count;
}
std::string score_uci(int score) {
    if (std::abs(score) > MATE - 500) {
        int distance = (MATE-std::abs(score)+1)/2;
        return "mate " + std::to_string(score >= 0 ? distance : -distance);
    }
    return "cp " + std::to_string(score);
}
int go_time(const Board& board, const std::vector<std::string>& tokens, int& depth) {
    depth = 64;
    int movetime=-1, wtime=0, btime=0, winc=0, binc=0, movestogo=30;
    bool infinite=false;
    for (size_t i=0; i<tokens.size(); ++i) {
        auto &t=tokens[i];
        if (t=="infinite") infinite=true;
        if (i+1<tokens.size()) {
            int n=0;try { n=std::stoi(tokens[i+1]); }catch(...) { continue; }
            if(t=="depth") depth=std::max(1,std::min(64,n));
            else if(t=="movetime") movetime=std::max(1,n);
            else if(t=="wtime") wtime=std::max(0,n);
            else if(t=="btime") btime=std::max(0,n);
            else if(t=="winc") winc=std::max(0,n);
            else if(t=="binc") binc=std::max(0,n);
            else if(t=="movestogo") movestogo=std::max(1,n);
        }
    }
    if (movetime>0) return movetime;
    if (infinite || (std::find(tokens.begin(),tokens.end(),"depth")!=tokens.end() &&
        std::find(tokens.begin(),tokens.end(),"wtime")==tokens.end())) return -1;
    int rem=board.sideToMove()==Color::WHITE?wtime:btime;
    int inc=board.sideToMove()==Color::WHITE?winc:binc;
    if (rem>0) return std::max(10,std::min(rem*7/10,rem/std::max(12,movestogo)+6*inc/10));
    return 500;
}

} // namespace

int main(int argc, char** argv) {
    if (argc > 1 && std::string(argv[1])=="--perft") {
        if(argc<4) return 2;
        Board b(argv[2]);
        std::cout << perft(b,std::atoi(argv[3])) << '\n';
        return 0;
    }
    if (argc > 1 && std::string(argv[1])=="--bench") {
        if(argc<4) return 2;
        Board b(argv[2]);
        std::atomic<bool> flag{false}; Search s(flag);
        auto r=s.run(b,64,std::atoi(argv[3]));
        std::cout << "{\"depth\":" << r.depth << ",\"nodes\":" << r.nodes
                  << ",\"seconds\":" << r.seconds << ",\"nps\":"
                  << static_cast<uint64_t>(r.nodes/std::max(1e-9,r.seconds))
                  << ",\"bestmove\":\"" << uci::moveToUci(r.move)
                  << "\",\"score\":" << r.score << "}\n";
        return 0;
    }
    Board board;
    std::thread worker;
    std::atomic<bool> stop{false};
    auto join = [&] {stop.store(true); if(worker.joinable())worker.join(); stop.store(false);};
    std::string line;
    while (std::getline(std::cin,line)) {
        std::istringstream stream(line);
        std::string cmd; stream >> cmd;
        if(cmd=="uci") {
            output("id name GM-1000 v0.8 King Safety Candidate");
            output("id author GM-1000 project");
            output("uciok");
        } else if(cmd=="isready") output("readyok");
        else if(cmd=="setoption") {
            // No user-configurable engine options yet; fail closed rather than claiming support.
        } else if(cmd=="stop") join();
        else if(cmd=="quit") {join();break;}
        else if(cmd=="ucinewgame") {join();board=Board();}
        else if(cmd=="position") {
            join();
            std::string type;stream>>type;
            try {
                if (type=="startpos") board=Board();
                else if(type=="fen") {
                    std::string fen,part;
                    for(int i=0;i<6;i++){if(!(stream>>part)) throw std::runtime_error("bad fen"); if(i)fen+=' ';fen+=part;}
                    board=Board(fen);
                } else {output("info string invalid position command");continue;}
                std::string keyword;stream>>keyword;
                if(keyword=="moves") {
                    std::string u;
                    while(stream>>u) {
                        Move m=uci::uciToMove(board,u);
                        Movelist legal;movegen::legalmoves(legal,board);
                        if(m.move()==Move::NO_MOVE || std::find(legal.begin(),legal.end(),m)==legal.end())
                            throw std::runtime_error("illegal UCI move: "+u);
                        board.makeMove(m);
                    }
                }
            } catch(const std::exception& e) {output(std::string("info string position error: ")+e.what());}
        } else if(cmd=="go") {
            join();
            std::vector<std::string> args;
            std::string s;while(stream>>s)args.push_back(s);
            int depth=64,millis=go_time(board,args,depth);
            Board copy=board;
            worker=std::thread([copy,depth,millis,&stop]() mutable {
                try {
                    Search engine(stop);
                    auto r=engine.run(copy,depth,millis,[](const Result& r){
                        std::ostringstream out;
                        out<<"info depth "<<r.depth<<" nodes "<<r.nodes<<" score "<<score_uci(r.score)
                           <<" time "<<int(r.seconds*1000)<<" nps "<<uint64_t(r.nodes/std::max(1e-9,r.seconds));
                        output(out.str());
                    });
                    output(std::string("bestmove ")+(r.move.move()==Move::NO_MOVE?"0000":uci::moveToUci(r.move)));
                } catch (const std::exception& e) {
                    output(std::string("info string native search error: ")+e.what());
                    output("bestmove 0000");
                }
            });
        }
    }
    join();
}