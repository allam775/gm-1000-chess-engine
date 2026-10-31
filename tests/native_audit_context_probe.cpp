// Compile as a separate executable; production source remains a normal UCI app.
#define main gm1000_uci_main
#include "../native/gm1000.cpp"
#undef main
#include <cassert>

int main() {
    std::atomic<bool> stop{false};
    Board fresh("7k/8/8/8/8/8/8/KQ6 w - - 0 1");
    Board old("7k/8/8/8/8/8/8/KQ6 w - - 99 1");
    Search warm(stop), cold(stop);
    const int score = warm.negamax(fresh, 1, -INF, INF, 0);
    const int warm_old = warm.negamax(old, 1, -INF, INF, 0);
    const int cold_old = cold.negamax(old, 1, -INF, INF, 0);
    assert(fresh.hash() == old.hash());
    assert(score > 0 && warm_old == 0 && cold_old == 0);

    // Poison a valid board match under a different reversible history.
    // It must remain useful for ordering, without supplying a score cutoff.
    Search guarded(stop), clean(stop);
    const uint64_t actual_context = 1234567, other_context = 7654321;
    auto& entry = guarded.tt[fresh.hash() & (guarded.tt.size()-1)];
    entry.key = fresh.hash(); entry.context = score_context(fresh, other_context);
    entry.depth = 20; entry.score = -12345; entry.flag = 0;
    const int guarded_score = guarded.negamax(fresh, 1, -INF, INF, 0, actual_context);
    const int clean_score = clean.negamax(fresh, 1, -INF, INF, 0, actual_context);
    assert(guarded_score == clean_score && guarded_score > 0);

    // Same board/clock after different reversible move orders: distinct context.
    auto play = [](const std::vector<std::string>& moves) {
        Board b; uint64_t context = 0;
        for (const auto& text : moves) {
            const auto parent = b.hash();
            const auto move = uci::uciToMove(b, text);
            assert(b.isLegal(move)); b.makeMove(move);
            context = next_context(context, parent, b);
        }
        return std::make_pair(b, context);
    };
    auto a = play({"g1f3","g8f6","b1c3","b8c6"});
    auto b = play({"b1c3","b8c6","g1f3","g8f6"});
    assert(a.first.hash() == b.first.hash());
    assert(a.first.halfMoveClock() == b.first.halfMoveClock());
    assert(score_context(a.first,a.second) != score_context(b.first,b.second));
    Board reset = a.first; const auto parent = reset.hash();
    reset.makeMove(uci::uciToMove(reset,"e2e4"));
    assert(next_context(a.second,parent,reset) == 0);
    std::cout << "fresh=" << score << " warm99=" << warm_old
              << " cold99=" << cold_old << " history_guard=" << guarded_score << '\n';
}
