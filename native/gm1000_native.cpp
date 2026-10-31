// GM-1000 native independent alpha-beta search core (C++17).
// Uses Disservin/chess-library for chess rules ONLY; move selection, search,
// evaluation, time controls, and UCI driver are GM-1000 code.
#include "chess.hpp"
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>
using namespace chess;
namespace {
constexpr int INF=32000, MATE=30000;
const int VALUES[6]={100,320,335,500,900,0};
struct Entry {int depth=0,score=0,flag=0;Move best{};}; // 0 exact, 1 lower, 2 upper
struct Timeout {};
struct Searcher {
 Board b;
 std::unordered_map<std::uint64_t,Entry> tt;
 std::chrono::steady_clock::time_point deadline;
 std::uint64_t nodes=0;
 bool timed=false;
 explicit Searcher(Board board):b(std::move(board)) {tt.reserve(65536);}
 void check() {if(timed && (nodes & 511u)==0 && std::chrono::steady_clock::now()>=deadline) throw Timeout{};}
 int eval() {
  int total=0;
  // Symmetric material and modest centering/development, no position memory.
  for(int i=0;i<64;i++){
   Piece p=b.at(Square(i)); if(p==Piece::NONE) continue;
   int kind=static_cast<int>(p.type());
   if(kind<0||kind>=6) continue;
   int file=i%8,rank=i/8;
   int relative=p.color()==Color::WHITE?rank:7-rank;
   int center=7-(std::abs(file-3)+std::abs(rank-3));
   int bonus=0;
   if(kind==0) bonus=relative*5+(3-std::abs(file-3))*3;
   else if(kind==1||kind==2) bonus=center*(kind==1?5:3);
   else if(kind==3) bonus=relative;
   int sign=p.color()==Color::WHITE?1:-1;
   total+=sign*(VALUES[kind]+bonus);
  }
  return b.sideToMove()==Color::WHITE?total:-total;
 }
 int ordered(const Move m, Move pv) {
  if(m==pv) return 1000000;
  if(b.isCapture(m)) {
   auto a=b.at(m.from()),v=b.at(m.to());
   int attacker=static_cast<int>(a.type()),victim=static_cast<int>(v.type());
   if(m.typeOf()==Move::ENPASSANT) victim=0;
   return 20000+(victim>=0&&victim<6?10*VALUES[victim]:0)-(attacker>=0&&attacker<6?VALUES[attacker]:0);
  }
  if(m.typeOf()==Move::PROMOTION) return 15000;
  return 0;
 }
 int quiesce(int alpha,int beta,int ply,int qdepth=0){
  ++nodes;check();
  if(b.isRepetition(2)||b.halfMoveClock()>=100||b.isInsufficientMaterial()) return 0;
  bool checknow=b.inCheck();
  if(ply>=32) return eval();
  if(!checknow){
   int stand=eval();
   if(stand>=beta)return beta;
   if(stand>alpha)alpha=stand;
   if(qdepth>=10)return alpha;
  }
  Movelist moves;
  if(checknow)movegen::legalmoves(moves,b);
  else movegen::legalmoves<MoveGenType::CAPTURE>(moves,b);
  if(moves.empty()&&checknow)return -MATE+ply;
  // Quiet promotion may be important in endgames; fully covered by main search.
  std::vector<std::pair<int,Move>> order;
  order.reserve(moves.size());
  for(const auto m:moves)order.push_back({ordered(m,Move{}),m});
  std::sort(order.begin(),order.end(),[](auto& x,auto& y){return x.first>y.first;});
  for(auto const& [priority,m]:order){
   b.makeMove(m);
   int score;
   try{score=-quiesce(-beta,-alpha,ply+1,qdepth+1);}
   catch(...){b.unmakeMove(m);throw;}
   b.unmakeMove(m);
   if(score>=beta)return beta;
   if(score>alpha)alpha=score;
  }
  return alpha;
 }
 int negamax(int depth,int alpha,int beta,int ply){
  ++nodes;check();
  if(b.isRepetition(2)||b.halfMoveClock()>=100||b.isInsufficientMaterial()) return 0;
  if(depth<=0)return quiesce(alpha,beta,ply);
  if(ply>=64)return eval();
  auto key=b.hash();
  auto it=tt.find(key);
  Move pv{};
  int original=alpha;
  if(it!=tt.end()){
   pv=it->second.best;
   if(it->second.depth>=depth && std::abs(it->second.score)<MATE-256){
    const auto& e=it->second;
    if(e.flag==0)return e.score;
    if(e.flag==1)alpha=std::max(alpha,e.score);
    if(e.flag==2)beta=std::min(beta,e.score);
    if(alpha>=beta)return e.score;
   }
  }
  Movelist moves;movegen::legalmoves(moves,b);
  if(moves.empty())return b.inCheck()?-MATE+ply:0;
  std::vector<std::pair<int,Move>> order;
  order.reserve(moves.size());
  for(auto const m:moves)order.push_back({ordered(m,pv),m});
  std::sort(order.begin(),order.end(),[](auto& x,auto& y){return x.first>y.first;});
  int best=-INF;Move bestmove{};
  for(auto const& [priority,m]:order){
   b.makeMove(m);
   int score;
   try{score=-negamax(depth-1,-beta,-alpha,ply+1);}
   catch(...){b.unmakeMove(m);throw;}
   b.unmakeMove(m);
   if(score>best){best=score;bestmove=m;}
   alpha=std::max(alpha,score);
   if(alpha>=beta)break;
  }
  if(tt.size()>500000)tt.clear();
  tt[key]={depth,best,best<=original?2:(best>=beta?1:0),bestmove};
  return best;
 }
 struct Result {Move move{};int score=0,depth=0;std::uint64_t nodes=0;};
 Result go(int movetime,int maxdepth){
  Movelist root;movegen::legalmoves(root,b);
  if(root.empty())return {};
  Move chosen=root[0];
  Result result{chosen,0,0,0};
  timed=movetime>=0;
  if(timed)deadline=std::chrono::steady_clock::now()+std::chrono::milliseconds(std::max(1,movetime));
  nodes=0;
  for(int d=1;d<=std::min(40,maxdepth);d++){
   try{
    if(timed&&std::chrono::steady_clock::now()>=deadline)break;
    std::vector<std::pair<int,Move>> order;
    order.reserve(root.size());
    for(auto const m:root)order.push_back({ordered(m,chosen),m});
    std::sort(order.begin(),order.end(),[](auto& x,auto& y){return x.first>y.first;});
    Move best{};int score=-INF,alpha=-INF,beta=INF;
    for(auto const& [priority,m]:order){
     if(timed&&std::chrono::steady_clock::now()>=deadline)throw Timeout{};
     b.makeMove(m);
     int value;
     try{value=-negamax(d-1,-beta,-alpha,1);}
     catch(...){b.unmakeMove(m);throw;}
     b.unmakeMove(m);
     if(value>score){score=value;best=m;}
     alpha=std::max(alpha,value);
    }
    if(best!=Move{}){
     chosen=best;result={best,score,d,nodes};
     std::cout<<"info depth "<<d<<" nodes "<<nodes<<" score cp "<<score<<" pv "<<uci::moveToUci(best)<<std::endl;
    }
    if(std::abs(score)>=MATE-100)break;
   }catch(const Timeout&){break;}
  }
  result.nodes=nodes;
  return result;
 }
};
int perft(Board& b,int depth){
 if(depth==0)return 1;
 Movelist moves;movegen::legalmoves(moves,b);
 int nodes=0;
 for(auto m:moves){b.makeMove(m);nodes+=perft(b,depth-1);b.unmakeMove(m);}
 return nodes;
}
}
int main(int argc,char** argv){
 std::ios::sync_with_stdio(false);std::cin.tie(nullptr);
 if(argc>1&&std::string(argv[1])=="--perft"){
  int depth=argc>2?std::atoi(argv[2]):3;
  Board b;std::cout<<perft(b,depth)<<"\n";return 0;
 }
 Board board;
 std::string line;
 while(std::getline(std::cin,line)){
  std::istringstream in(line);std::string cmd;in>>cmd;
  if(cmd=="uci"){
   std::cout<<"id name GM-1000 Native v0.6 experimental\nid author GM-1000 project\nuciok\n"<<std::flush;
  }else if(cmd=="isready")std::cout<<"readyok"<<std::endl;
  else if(cmd=="ucinewgame")board=Board();
  else if(cmd=="position"){
   std::string type;in>>type;
   if(type=="startpos")board=Board();
   else if(type=="fen"){
    std::string fen="",token;
    for(int i=0;i<6&&in>>token;i++){if(i)fen+=" ";fen+=token;}
    board=Board(fen);
   }
   std::string token;
   if(in>>token&&token=="moves"){
    while(in>>token){
     Move m=uci::uciToMove(board,token);
     if(m==Move{}||!board.isLegal(m)){std::cerr<<"illegal position move "<<token<<"\n";break;}
     board.makeMove(m);
    }
   }
  }else if(cmd=="go"){
   int time=200,depth=64;std::string x;
   while(in>>x){if(x=="movetime")in>>time;else if(x=="depth")in>>depth;}
   Searcher engine(board);auto result=engine.go(time,depth);
   std::cout<<"bestmove "<<(result.move==Move{}?"0000":uci::moveToUci(result.move))<<std::endl;
  }else if(cmd=="quit")break;
 }
}
