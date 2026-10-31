# ♟️ GM-1000 Chess Engine

## 🚀 NEW: GM-1000 v0.6 native C++ search (experimental)

A standalone C++17 UCI engine is available under [`native/`](native/README.md), using a pinned MIT chess-rule library and an independently written evaluation and search. It reached median depth **6 vs 2** for the Python engine on the same 16 test positions under 0.2s/move, and won **24/24** paired-opening games directly against the Python baseline with both histories off. This is *not* a 2500 Elo claim or automatic promotion. The native engine is **experimental and opt-in**; default play remains the Python implementation until independent tournament validation. [Evidence](data/native_v06_benchmark_report.json) · [Windows/Linux builds](https://github.com/allam775/gm-1000-chess-engine/actions/workflows/native-portable.yml).

**محرك شطرنج تجريبي مستقل | النسخة `v0.1` | ميزانية المشروع: 0 جنيه**

> **حالة المشروع:** نموذج أولي قابل للاختبار، وليس محركًا مثبتًا بمستوى Grandmaster. يملك خوارزمية بحث وتقييم خاصة به، ويستخدم مكتبة `python-chess` لتطبيق قواعد اللعبة والتواصل مع محركات الشطرنج. لا يستخدم Stockfish لاتخاذ نقلاته؛ يُستخدم Stockfish **كمنافس** في الاختبارات.

## ♟️ GM-1000 v0.2 — 200 titled-grandmaster game study

The previous v0.1 outcome-only learning algorithm was **retired** after its
20-tournament audit (80 games; 25 wins, 9 draws, 46 losses against Stockfish
Skill 0). It incorrectly assigned the final match outcome to every earlier
opening move and used an incomplete evaluation gradient. Those historical
results remain in `data/learning_report.json` and `data/learning_state.json`,
but **they are not the approved engine's weights**.

The v0.2 implementation:

- Selects **at least 200 unique, fully recorded titled-GM games** from eight
  champion player archives (Carlsen, Kasparov, Fischer, Karpov, Anand, Tal,
  Botvinnik, Alekhine), and records a fingerprint and source for each.
- Splits games by player into a deterministic, disjoint 80% training and
  20% holdout. Samples middle/late-game positions from the **named GM's own
  side**, rather than pretending every opponent's move is a GM move.
- Ranks each observed GM move against the strongest-looking legal alternatives
  using a **correct pairwise logistic gradient**. Material is kept fixed;
  positional-feature weights stay bounded and regularized.
- Writes a detailed report, 200-game provenance index, and an **unapproved
  candidate**, never `data/approved_model.json`. GM imitation does **not** prove
  chess strength: GMs can blunder, and a one-ply static comparison is not a
  tactical search or an Elo evaluation.
- Retains an independent **promotion gate**: offline validation must improve
  and the candidate must convincingly outperform the unchanged control in
  two matched-setting 100+ game tournament samples before someone explicitly
  approves it. A conservative 99%-confidence margin is enforced by
  `scripts/promote_candidate.py`. No automatic promotion occurs in the study.
- Loads only `data/approved_model.json` in default UCI play. If none exists,
  the engine uses the stable v0.1 evaluation, not the poorly trained weights.

Run manually from GitHub Actions: **GM-1000 v0.2 study 200 grandmaster games**.
On completion inspect `data/gm_study_report_v02.json`,
`data/gm_study_game_index_v02.json` and
`data/candidates/gm200-v02-candidate.json`. The historical 20-tournament
outcome trainer is disabled to prevent accidental retraining or promotion.

## 🎯 ما الهدف؟

تطوير محرك شطرنج مستقل يتدرج في القوة عبر ثلاث ركائز:

1. **دراسة 1,000 مباراة تاريخية مختارة** من مباريات كبار أساتذة الشطرنج لاستخراج أنماط الافتتاحيات.
2. **حساب النقلات بنفسه** باستخدام خوارزميات البحث وتقييم الأوضاع، بدل الاكتفاء بتقليد نقلات الماضي.
3. **إجراء بطولات قابلة للتكرار** ضد محركات أخرى، وتطوير كل إصدار اعتمادًا على النتائج المسجلة.

**الهدف الطموح:** الاقتراب تدريجيًا من مستوى Grandmaster، لكن لن نعلن أي تصنيف Elo أو قوة محددة إلا بعد اختبارات واسعة ومحايدة. كما أن تصنيف المحركات لا يساوي مباشرة تصنيف FIDE للاعبين البشر.

## 💸 قاعدة المشروع: صفر تكلفة

- الاعتماد على أدوات مفتوحة المصدر وبرمجيات مجانية.
- تشغيل التجارب الأولية عبر **GitHub Actions** في **مستودع عام (Public)** باستخدام الـstandard GitHub-hosted runners.
- عدم الاعتماد على GPU مدفوع أو خدمات API تجارية أو اشتراكات.
- تقسيم التجارب إلى دفعات محدودة، واحترام حدود استخدام GitHub وسياساته.
- **لا يوجد ما يضمن مجانية أي استخدام خارج الشروط المذكورة:** تشغيل Actions القياسي مجاني حاليًا للمستودعات العامة؛ تجنّب الـlarger runners والميزات المدفوعة. راجع [سياسة الفوترة الحالية](https://docs.github.com/en/actions/concepts/billing-and-usage) قبل التوسع.

> GitHub Actions وسيلة للأتمتة والاختبارات، وليست خادمًا دائمًا لتشغيل محرك الشطرنج دون توقف.

## ⚙️ كيف يعمل المحرك الآن؟

| الوحدة | الوضع في `v0.1` | وظيفتها |
|---|---|---|
| محرك اللعب | موجود | البحث في النقلات وتقييمها باستخدام `Negamax / Alpha-Beta` |
| البحث الهادئ | موجود | `Quiescence Search` لفحص التبادلات التكتيكية قبل التوقف |
| جدول المواقف | أساسي | تخزين نتائج بحث متكررة `Transposition Table` |
| ترتيب النقلات | أساسي | ترتيب الالتقاط والترقية و`Killer Moves` |
| تقييم الموقف | أولي | قيم القطع، المركز، تقدم البيادق، بنية البيادق وأمان الملك بصورة مبسطة |
| بروتوكول `UCI` | موجود | التواصل مع واجهات الشطرنج والمحركات المنافسة |
| كتاب الافتتاحيات | يُبنى عند تشغيل Workflow | استخراج تكرار النقلات من 1,000 مباراة مختارة |
| ساحة الاختبار | موجودة | مباريات ضد نسخة Stockfish التي تُثبت في بيئة الاختبار |
| تعلم عصبي / NNUE | **غير موجود بعد** | مرحلة تطوير مستقبلية |
| تصنيف Elo موثق | **غير متاح بعد** | يتطلب مباريات ومعايرة إحصائية |

**مهم:** «دراسة 1,000 مباراة» في الإصدار الحالي تعني **بناء كتاب افتتاحيات إحصائي** من النقلات، ولا تعني أن المحرك استخلص تلقائيًا مبادئ استراتيجية عامة من كامل المباريات أو خضع لتدريب شبكة عصبية.

## 🏆 من أين تأتي المباريات الألف؟

يستخدم البرنامج `scripts/build_book.py` مجموعات **PGN Mentor** الخاصة بعشرة أسماء بارزة:

**Magnus Carlsen · Garry Kasparov · Bobby Fischer · Anatoly Karpov · Viswanathan Anand · Mikhail Tal · José Raúl Capablanca · Paul Morphy · Mikhail Botvinnik · Alexander Alekhine**.

يقوم البرنامج بتحميل الملفات عند التشغيل، واستبعاد المباريات غير الصالحة أو القصيرة جدًا، وحذف التكرارات، ثم ترتيب المرشحين وفق معايير محددة مثل البطولة وطول المباراة والتصنيف المعلن (إن وجد)، مع محاولة موازنة تمثيل اللاعبين. بعد ذلك ينتقي **1,000 مباراة فريدة** ويبني كتابًا للافتتاحيات حتى أول **24 نصف نقلة (ply)**.

> لا يوجد معيار موضوعي واحد لتحديد «أعظم 1,000 مباراة». هذه **عينة تاريخية منتقاة بمنهج معلن** وليست ترتيبًا رسميًا لأفضل المباريات في التاريخ.

**المصدر:** [PGN Mentor](https://www.pgnmentor.com/files.html). يجب مراجعة شروط استخدام البيانات قبل إعادة نشر مجموعات PGN الأصلية. ملفات PGN الخام لا تُرفع تلقائيًا إلى المستودع؛ بل تُعرض مؤقتًا كـArtifact.

## 🚀 التشغيل عبر GitHub بدون أي تكلفة

### الخطوة 1: إنشاء المستودع

1. افتح [GitHub](https://github.com/new).
2. سمِّ المستودع: `gm-1000-chess-engine`.
3. حدّد **Public**، ثم أنشئ المستودع.
4. ارفع **محتويات** مجلد المشروع إلى جذر المستودع، وليس المجلد الخارجي وحده. تأكد من رفع المجلد المخفي `.github/workflows` أيضًا.
5. تأكد من ظهور الملفات `engine/` و`scripts/` و`requirements.txt` بجوار `README.md` في الصفحة الرئيسية.

### الخطوة 2: التأكد من أن الاختبارات تعمل

افتح تبويب **Actions** وستجد هذه المسارات:

| اسم Workflow الظاهر في GitHub | متى يعمل؟ | ماذا يفعل؟ |
|---|---|---|
| `Engine checks` | تلقائيًا عند الرفع، ويمكن تشغيله يدويًا | اختبارات Python والتأكد من استجابة بروتوكول UCI |
| `Study 1000 master games` | تشغيل يدوي | اختيار المباريات وبناء قاعدة الافتتاحيات |
| `Engine arena` | تشغيل يدوي | إجراء مباريات ضد Stockfish وحفظ تقرير النتائج |

إذا لم تظهر المسارات، تأكد أن GitHub Actions مفعّل وأن ملفات `.yml` موجودة داخل `.github/workflows/` في الفرع الافتراضي.

### الخطوة 3: بناء كتاب الافتتاحيات

1. انتقل إلى **Actions → Study 1000 master games**.
2. اضغط **Run workflow** ثم شغّل العملية على الفرع الافتراضي.
3. افتح نتيجة التشغيل وراجع السجلات؛ يجب أن تنتهي العملية بنجاح قبل اعتبار الكتاب مكتملًا.
4. عند النجاح يحاول الـWorkflow حفظ الملفين التاليين في المستودع:
   - `data/opening_book.json` — ذاكرة الافتتاحيات.
   - `data/selection_index.json` — بيانات اختيار المباريات ومصدر كل منها.
5. ستجد في **Artifacts** حزمة باسم `selected-master-games` تضم أيضًا `data/selected_1000.pgn` لفترة احتفاظ محدودة.

**ملاحظة للصلاحيات:** ملف الـWorkflow يطلب `contents: write` ليتمكن من حفظ الكتاب تلقائيًا. قد تمنع إعدادات المستودع أو حماية الفرع عملية `git push`؛ في هذه الحالة راجع سجل الخطأ وسياسات المستودع بدل منح صلاحيات أوسع بشكل عشوائي.

### الخطوة 4: بدء أول بطولة

1. انتقل إلى **Actions → Engine arena → Run workflow**.
2. ابدأ بالإعدادات التالية:

   | الإعداد | القيمة المقترحة لأول اختبار |
   |---|---|
   | `games` | `4` |
   | `stockfish_skill` | `0` |
   | `seconds_per_move` | `0.2` |

3. بعد اكتمال التشغيل، افتح **Artifacts → tournament-results**.
4. راجع الملفين:
   - `reports/matches.pgn` — النقلات الكاملة للمباريات.
   - `reports/results.json` — عدد الانتصارات والتعادلات والهزائم والأخطاء ونسبة النقاط.
5. بعد التأكد من الاستقرار، زِد عدد المباريات أو صعوبة المنافس **تدريجيًا**، مع إبقاء إعدادات المقارنة متطابقة بين الإصدارات.

**طريقة احتساب نسبة النقاط:**

```text
Score % = 100 × (Wins + 0.5 × Draws) / Completed games
```

**تنبيه:** قيمة `stockfish_skill` تتدرج عادةً من `0` إلى `20`، لكنها **ليست** تصنيف Elo. كذلك `Stockfish` هنا هو إصدار الحزمة المثبتة في بيئة GitHub، وقد يختلف عن أحدث إصدار رسمي.

## 💻 التشغيل محليًا (اختياري)

المطلوب: **Python 3.11** أو نسخة متوافقة، واتصال بالإنترنت لتثبيت الحزم. لا تحتاج إلى GPU لتشغيل الإصدار الأساسي، لكن الأداء على CPU محدود.

من جذر المشروع على Windows PowerShell:

```powershell
py -m pip install -r requirements.txt pytest
py -m pytest -q
py -u -m engine.uci
```

بعد تشغيل المحرك، يمكن إدخال أوامر بروتوكول UCI التالية واحدًا في كل سطر:

```text
uci
isready
position startpos
go movetime 300
quit
```

يمكن تشغيله في واجهة متوافقة مع **UCI** باستخدام أمر `python -u -m engine.uci`، بشرط تعيين **مجلد المشروع كمسار العمل**. هذا المشروع لا يتضمن واجهة شطرنج رسومية في النسخة الحالية.

لإنشاء كتاب الافتتاحيات محليًا (اختياري ويتطلب الإنترنت):

```powershell
py scripts/build_book.py --limit 1000
```

لتشغيل ساحة مباريات محليًا ستحتاج أيضًا إلى تثبيت Stockfish وتحديد مساره عبر متغير البيئة `STOCKFISH_PATH` إن لم يكن موجودًا في PATH.

## 🗂️ هيكل المشروع

```text
gm-1000-chess-engine/
├── .github/
│   └── workflows/
│       ├── ci.yml              # فحص واختبار الكود
│       ├── build-book.yml      # دراسة المباريات وبناء كتاب الافتتاحيات
│       └── arena.yml           # المباريات ضد Stockfish
├── data/
│   └── .gitkeep               # ملفات الكتاب تُولد لاحقًا
├── engine/
│   ├── __init__.py
│   ├── __main__.py
│   ├── search.py               # البحث والتقييم
│   └── uci.py                  # بروتوكول UCI
├── scripts/
│   ├── build_book.py          # اختيار المباريات وحفظ النتائج
│   └── arena.py               # إدارة المباريات وإحصاء نتائجها
├── tests/
│   └── test_core.py           # اختبارات أولية
├── requirements.txt
└── README.md
```

## 📈 خارطة طريق التطوير

- [x] إنشاء نواة لمحرك مستقل بقواعد شطرنج صحيحة عبر `python-chess`.
- [x] إضافة تقييم أولي للمواقف وبحث `Alpha-Beta`.
- [x] تجهيز نظام اختيار 1,000 مباراة وبناء كتاب افتتاحيات.
- [x] تجهيز `GitHub Actions` للاختبارات والبطولات.
- [ ] تشغيل بناء كتاب الافتتاحيات فعليًا وتوثيق نجاحه على GitHub.
- [ ] تشغيل أول بطولة فعلية وتسجيل خط الأساس.
- [ ] معالجة الأخطاء وتحسين إدارة الوقت والبحث.
- [ ] نقل الأجزاء الحساسة للأداء إلى **C++** أو **Rust** عند الحاجة.
- [ ] تطوير **Principal Variation Search** و**Late Move Reductions** وإدارة أفضل لجدول المواقف.
- [ ] تحويل مباريات الأساتذة إلى **مواقف تدريب وتقييم**، مع فصل بيانات التدريب عن الاختبار.
- [ ] تجربة ضبط دالة التقييم على بيانات موثوقة، وربما **NNUE** خفيفة لاحقًا إذا سمحت الموارد المجانية.
- [ ] مباريات مقارنة متعددة ضد مستويات ومحركات مختلفة، مع عكس الألوان وتوحيد الزمن.
- [ ] حساب تقدير قوة مدعوم بعينة كافية وفواصل ثقة، بدل إطلاق رقم Elo غير مثبت.

## 📊 كيف سنعرف أن المحرك يتحسن؟

لا نعتمد على فوز أو خسارة منفردة. لكل إصدار نحتفظ بنسخة الكود وإعدادات البطولة ونوثّق:

- عدد المباريات المكتملة، والانتصارات، والتعادلات، والهزائم.
- الأخطاء أو النقلات غير القانونية أو انهيارات المحرك.
- نسبة النقاط مقابل **المنافس نفسه** وتحت **نفس الزمن والموارد**.
- نتائج اللعب بالأبيض والأسود لتقليل الانحياز.
- سرعة البحث وعمقه عند الإمكان.
- عدد مباريات كافٍ لتقليل أثر المصادفة؛ **أربع مباريات مجرد فحص أولي وليست تقييم قوة**.

## ⚠️ حدود النسخة `v0.1`

1. المشروع **لم يثبت بعد** أنه درس الألف مباراة على GitHub أو فاز على محرك منافس؛ يلزم تشغيل الـWorkflows أولًا.
2. الاحتفاظ بكتاب افتتاحيات لا يساوي تدريب نموذج يتعلم التخطيط والتكتيك من كل المباراة.
3. سرعة Python محدودة مقارنة بمحركات C++ المتقدمة؛ تحسين البنية والخوارزميات سيكون ضروريًا.
4. لا توجد حاليًا شبكة عصبية مدربة أو قيمة Elo موثقة أو ضمان الوصول إلى مستوى Grandmaster.
5. بعض التنزيلات الخارجية قد تفشل أو تتغير؛ عندها نراجع سجل GitHub Actions ونحدّث مصدر البيانات بطريقة موثقة.

## 🔗 مصادر وروابط

- [GitHub Actions — الفوترة والاستخدام](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub Actions — إعدادات التشغيل والصلاحيات](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
- [PGN Mentor — مجموعات المباريات التاريخية](https://www.pgnmentor.com/files.html)
- [Lichess Database — مصدر بيانات بديل](https://database.lichess.org/)
- [python-chess](https://python-chess.readthedocs.io/)
- [Stockfish](https://stockfishchess.org/)

---

**فلسفة GM-1000:** لا نريد محركًا يحفظ النقلات ويكررها، بل محركًا يستطيع حساب نقلاته، والتعلم من نتائج الاختبارات، وإظهار تطوره بالأرقام — **مع الالتزام بميزانية صفر جنيه**.

## ✅ تنفيذ ملفات المشروع واختبارها

يتضمن هذا الأرشيف **الشيفرة المصدرية الكاملة** للوحدات الموضحة أعلاه، مع ثلاثة ملفات GitHub Actions واختبارات أولية. **بناء الملفات لا يعني نجاح تشغيلها عند عدم توافر حزمة `chess` أو Stockfish**؛ راجع `RUN_STATUS.md` للاطلاع على نتائج التحقق الفعلية في بيئة الإنشاء.

بعد تثبيت الاعتماديات، يُنصح بالتشغيل بهذا الترتيب:

```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
python -u -m engine.uci
# In a separate invocation, once tests pass:
python scripts/build_book.py --limit 1000
python scripts/arena.py --games 4 --stockfish-skill 0 --seconds-per-move 0.2
```

أثناء التشغيل اليدوي عبر UCI، أرسل أوامر `uci`، ثم `isready`، ثم `position startpos`، ثم `go movetime 300`، وانتظر رسالة `bestmove` قبل `quit`. تعتمد ساحة الاختبار على وجود برنامج Stockfish ضمن `PATH` أو المتغير `STOCKFISH_PATH`.

**الترخيص والبيانات:** مكتبة `chess` (python-chess) مرخصة وفق GPL-3.0-or-later؛ يُرجى مراعاة التزامات ترخيصها عند توزيع الأعمال المشتقة، والتحقق من شروط نشر مجموعات PGN قبل إعادة نشرها. لا يتضمن الأرشيف بيانات PGN الخام المحمّلة من الإنترنت.

## 🧠 20 tournament incremental learning experiment

This revision adds a **real, auditable online learning loop**, not a neural network and not a guarantee of becoming stronger:

- **20 sequential mini-tournaments × 4 games each**, with colors alternated and unchanged Stockfish Skill 0 and 0.1 seconds per move. It is a total of **80 training games**, plus two independent **8-game holdout comparisons**.
- After **each** 4-game tournament, GM-1000 records the results of its opening choices (win +1, draw 0, loss -1) and updates nine **bounded non-material positional evaluation weights** via a small outcome-gradient step. Opponent moves and Stockfish analyses are **not** used as oracle labels.
- The next tournament starts a fresh engine process, loading the **previous round's** saved learned state from `data/learning_state.json`. The engine never trains between games within one mini-tournament.
- Every round produces its own `matches.pgn`, `results.json`, and `learning_update.json`; `rounds.csv` and `summary.json` provide the full audit trail.
- Two held-out evaluations at the end use the same conditions **without training**: an untrained version (`Learning = false`) and the learned version (`Learning = true`). Even if the score rises, a small evaluation sample does not prove genuine strength gains.
- The learning results and weights are saved to `data/learning_report.json` and `data/learning_state.json` once the full workflow succeeds. Full match PGN files are downloadable in the GitHub Actions artifact.

Run **Actions → Learn from 20 Stockfish tournaments → Run workflow**, or run locally (Python dependencies and Stockfish required):

```bash
python scripts/learn_series.py --rounds 20 --games 4 --stockfish-skill 0 --seconds-per-move 0.1 --eval-games 8
```

`Engine` additionally recognizes UCI `setoption name Learning value true|false`; material coefficients are fixed and learned non-material coefficients are clipped in `[0.4, 1.6]`. The feature-learning rule is deliberately simple, with no claim of stable generalization, NNUE or Elo calibration. This workflow is a **bounded batch experiment**, not a background cloud worker.


## Position memory — v0.3 (exact grandmaster positions)

**Current verified database: 560 distinct source games, 32,233 exact positions, 32,728 position–move pairs and 35,157 observations.** The expansion is append-only; new game fingerprints and provenance are in `data/position_memory_expansion_index.json`, with a complete count audit in `data/position_memory_report.json`.


In addition to the 24-ply opening book, the engine supports a **persistent database of exact board positions from studied grandmaster games**, including middlegame positions. To build it, run **Build GM position memory from 200-game study** in GitHub Actions.

- The database is stored in `data/position_memory.json` and its provenance/counts in `data/position_memory_report.json`. It initially used the **160 training games** of the reproducible 200-game grandmaster study. The audited [400-game expansion](https://github.com/allam775/gm-1000-chess-engine/actions/runs/41192151772) added **400 completely different grandmaster games**, excluding all 200 original study games and the separate 1,000 opening-book study games. The **40 validation games remain excluded**.
- For each position (EPD: board, turn, castling and legal en passant), it stores legal move UCI IDs, the number of times a **named grandmaster** made the move, and player counts; positions beyond the opening book are included (up to ply 180). It does not store raw chess engine scores or assert that any observed move is objectively best.
- On each move, UCI GM-1000 first looks up the current position. If found, remembered moves are searched first by alpha-beta; they can be preferred **only within 20 centipawns of the best searched move**, never over detected mates. If the position is unknown, it uses its existing historical opening book or regular alpha-beta search. This is **exact position lookup**, not fuzzy generalization.
- UCI toggle: `setoption name PositionMemory value false` to disable memory and run the same engine as a control. The on-disk database is reloaded on `ucinewgame`. No rejected evaluation-weight candidates are deployed.
- Actual performance versus the memory-disabled control still requires paired playing-strength tests. The database's mere existence is not proof the engine got stronger.
