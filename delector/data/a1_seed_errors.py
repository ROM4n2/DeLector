# -*- coding: utf-8 -*-
"""判定量仪器 A 的冻结种子集：五类 held-out 德语错误（probe）+ 每篇一处语法族信号（signal）。

用途（设计稿 §3 仪器 A）
------------------------
§4.3 第 8 条对照实验的**唯一判决量**是 `R_uncovered` = 「注入的 `right` 是否回到循环
输出文本」的确定性回收率。本模块提供其全部真值：20 篇底本、每篇 = 1 处 signal + ≥3 处
probe、每处带 `wrong`（已注入文本里的错误形态）与 `right`（修复目标形态）。

2026-10-15 修订：注入分两类（`Injection.kind`）
----------------------------------------------
实测（生产分流 `routes.main.violations_for` + `_text_kind`）：只注入 held-out 错误时
**全部 20 篇 `v_0 == 0`**（判定量口径，即被计数违规为零）⇒ A3 臂**首轮即收敛、根本不
迭代**、`A2 vs A3` 的自变量（裁判信号）恒为零 ⇒ 实验对「裁判信号是否有价值」不可识别。
故：

- `kind="signal"`（**不进判决量**，每篇恰好 1 处）：属**语法族**（对 letter / prose 都被
  生产分流计数）⇒ 该篇 `v_0 == 1`，循环才会真迭代；
- `kind="probe"`（**判决量分子**，每篇 ≥3 处）：五类 held-out 错误（原口径不变）；
- 二者 MUST NOT 文字区间重叠（区间层测试逐处钉死）。

signal 选点纪律（逐条实测标定，换信号/换句式前先读）
----------------------------------------------------
- 首选**规则 B（固定介词支配格）**：期望格来自介词/搭配表，不随注入后的解析漂移 ⇒
  检出稳定（`kasus`；动词固定搭配源报 `praeposition`）。
- **规则 A（冠词）**只在名词有**词典性别权威**的位置稳定（`Wohnung` / `Anmeldung` /
  `Termin` / `Möglichkeit`…）；对无词典词条的复合词（`A1-Kurs` 等），spaCy 会随新冠词
  改写性/数形态让句子"自洽" ⇒ 静默漏报。
- 避开会被**重挂到支配格词表动词**名下的宾语位：如 `einen Salat` 改 `eine Salat` 后被
  挂到 `trinken`（Acc 词表）⇒ `artikel + rektion` 双报（`v_0 == 2`，同理也威胁形态）。
- signal 与任何 probe 的字符串互不为子串（双向回放测试同时钉住）。

五类为何是 A1 经典错、又为何「当前六个检测器抓不到」（逐条对 `services/writing.py` 核过）
----------------------------------------------------------------------------------------
1. `nebensatz_wortstellung`（从句语序：定式动词未居末）—— 规则 E
   （`detect_verb_second_position`）只判**主句** V2；从句谓词（dep ∈ mo/oc/cp/…）被
   显式排除 ⇒ 从句内的错位不在其视野。
2. `artikel_genus`（冠词/限定词性别）—— ⚠️ 必须小心：规则 A
   （`detect_determiner_noun_agreement`）**确实覆盖**「DET 与名词性/数不一致」的多数
   直陈位置 —— 所以本种子集把该类注入**全部限定在双向介词（in/an/auf/über/…）短语内**：
   规则 A 对「名词直接受介词支配」的 DET 显式让位给规则 B，而规则 B 对 twoway 整组跳过
   ⇒ 该位置才真 held-out（由 `tests/test_a1_seed_errors_data.py` 用真实 spaCy 逐篇钉住）。
3. `verb_kongruenz`（动词人称/数变位）—— 规则 C（`detect_subject_verb_agreement`）只判
   「复数主语 + 单数定式动词」**一个方向**（源码 docstring 明说反向不判）；本种子集的
   错形一律挂在**单数主语**（ich/du/er/…）上 ⇒ 落在其判据之外。
4. `praeposition_kollokation`（介词固定搭配选错）—— 规则 B/D 判的是**介词支配的格**
   （`kasus`/`praeposition`/`rektion`），不判「介词本身是否是该动词的正确搭配」；
   替换后的介词与后续 NP 的格表面相容（或 NP 为代词/零冠词）⇒ 不被报。
5. `nomen_grossschreibung`（名词首字母误小写）—— 六个检测器均无大小写检查 ⇒ 完全未覆盖。

素材来源（硬要求：MUST 取自仓内既有真实德语素材，**无自造长文**）
------------------------------------------------------------------
- 书信 10 篇：`delector/data/a1_writing_dict.py::A1_SCHREIBEN_TEIL2` 的 10 篇官方
  `sample_email`（`clean_text` = 范文**逐字**复制；`text` = 反向注入后的版本）。
- 散文 10 篇：`delector/data/corpus_dict.py::OFFICIAL_CORPUS` 按表内顺序取**前 10 篇
  非书信体课文**（跳过书信体 `goethe_a2_alltag_03`；即 A1×2 + A2×1 + B1×3 + B2×2 +
  TestDaF×2），`clean_text` = 课文 `content` **逐字整篇复制**。
  **无任何拼接**：每篇是一个完整课文，未加连接词、未增删句子。
- 测试双向锚：`clean_text` MUST 与上游素材逐字相等、20 篇互不相同 ⇒ 任何手抄漂移都红。

注入构造纪律
------------
- `text` 不是手抄字面量，而是 `_inject(clean_text, injections)` 的确定性结果
  （判决量依赖「text 与 clean_text 的差异**恰好**是注入」，构造方式即证明的一部分）；
- **probe** 注入 `wrong`/`right` 的字母词计数（`[a-zA-ZäöüÄÖÜß]+`）相同、**signal**
  允许 ±1 词（如 `zu Hause → zu der Hause`）：两类都实测未跨过 `a1_word_count` 阈值
  —— 裁判计数差分 == 恰好 signal 一条，由 held-out 层逐篇钉死；注入位置避开书信正文
  首词与称呼语/结语行 ⇒ 不触碰格式族其余规则；
- 注入片段自带足够上下文（多数在篇内唯一），保证「`wrong` 在 `text` 中计数 ==
  `expected_count` 且 `right` 在 `clean_text` 中计数 == `expected_count`」逐条可复算；
- 五类 probe 逐条手工撰写、逐条用真实 spaCy 实跑验证 held-out（三重差分见测试文件）；
  signal 逐条实跑验证 `violations_for(...) == [该条]`；
- 2026-10-15 两处 probe 换位（为给 signal 腾出没有探针覆盖的位点）：`letter_01` 的
  nomen 探针由 `einen salat` 换到 `am samstag`；`letter_08` 由 `die anmeldung` 换到
  `a1-kurs`（两处仍为 held-out，判决口径不变）。
"""

from dataclasses import dataclass

ERROR_CLASSES: tuple[str, ...] = (
    "nebensatz_wortstellung",
    "artikel_genus",
    "verb_kongruenz",
    "praeposition_kollokation",
    "nomen_grossschreibung",
)


@dataclass(frozen=True, slots=True)
class Injection:
    """一处注入：`wrong`（错误形态）→ `right`（修复目标形态）。

    `kind` 取值仅两种（2026-10-15 修订，见模块头）：
    - `"signal"`：语法族、被生产分流计数 ⇒ 每篇**恰好 1 处**（该篇 `v_0 == 1` 的物理
      保证；**不进判决量**）；
    - `"probe"`：五类 held-out 之一，判决量分子（每篇 ≥3 处）。
    """

    error_class: str
    kind: str
    wrong: str
    right: str
    expected_count: int


@dataclass(frozen=True, slots=True)
class SeedCase:
    """一篇种子文本：`text` 已含注入，`clean_text` 是修复后的目标文本。"""

    id: str
    text: str
    clean_text: str
    injections: list[Injection]


def _inject(clean: str, injections: list[Injection]) -> str:
    """把 `clean` 中每条注入的 `right` 全部替换为 `wrong`（`text` 的唯一构造路径）。

    为什么 `text` 不做手写字面量：手抄整文会引入与注入列表无关的抄写误差，而本实验的
    判决量正是「`right` 是否回到文本」——`text` 与 `clean_text` 的差异 MUST 恰好是注入
    本身，故由注入列表确定性构造（测试同时钉住「`text` == 回放注入」与「回放修复 ==
    `clean_text`」双向一致，任何手改都会红）。
    """
    text = clean
    for inj in injections:
        text = text.replace(inj.right, inj.wrong)
    return text


# ── 书信 10 篇（底本 = 官方 A1_SCHREIBEN_TEIL2 范文，反向注入）────────────────────────

_L1_CLEAN: str = (
    "Liebe Lisa,\n\nich lade dich herzlich zu meiner Geburtstagsparty am Samstag um 19 Uhr bei mir zu Hause ein. "
    "Kannst du vielleicht einen Salat oder etwas zu trinken mitbringen?\n\nViele Grüße\nAnna"
)

_L1_INJECTIONS: list[Injection] = [
    # signal：固定介词 zu 支配三格，"zu Hause"（固定表达）被写坏成 "zu der Hause"（v_0 == 1）。
    Injection(error_class="kasus", kind="signal", wrong="zu der Hause", right="zu Hause", expected_count=1),
    Injection(
        error_class="verb_kongruenz",
        kind="probe",
        wrong="Können du vielleicht",
        right="Kannst du vielleicht",
        expected_count=1,
    ),
    Injection(
        error_class="praeposition_kollokation",
        kind="probe",
        wrong="für meine Geburtstagsparty",
        right="zu meiner Geburtstagsparty",
        expected_count=1,
    ),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="am samstag", right="am Samstag", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="ich ladet dich", right="ich lade dich", expected_count=1),
]

_L2_CLEAN: str = (
    "Sehr geehrte Damen und Herren,\n\nleider kann ich meinen Termin am Mittwoch um 10 Uhr nicht wahrnehmen, "
    "weil ich arbeiten muss. Können wir den Termin auf nächste Woche verschieben?\n\nMit freundlichen Grüßen\n"
    "Max Mustermann"
)

_L2_INJECTIONS: list[Injection] = [
    # signal：四格宾语 "meinen Termin" 丢词尾写成 "mein Termin"（冠词一族，v_0 == 1）。
    Injection(error_class="artikel", kind="signal", wrong="mein Termin", right="meinen Termin", expected_count=1),
    Injection(
        error_class="nebensatz_wortstellung",
        kind="probe",
        wrong="weil ich muss arbeiten",
        right="weil ich arbeiten muss",
        expected_count=1,
    ),
    Injection(
        error_class="praeposition_kollokation",
        kind="probe",
        wrong="für nächste Woche",
        right="auf nächste Woche",
        expected_count=1,
    ),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="leider können ich", right="leider kann ich", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="am mittwoch", right="am Mittwoch", expected_count=1),
]

_L3_CLEAN: str = (
    "Sehr geehrter Herr Becker,\n\nich interessiere mich sehr für Ihre 2-Zimmer-Wohnung. Ich arbeite als Ingenieur "
    "und suche eine Wohnung für mich allein. Wann kann ich die Wohnung besichtigen?\n\nMit besten Grüßen\nDavid Chen"
)

_L3_INJECTIONS: list[Injection] = [
    # signal：四格宾语 "die Wohnung" 被换成中性冠词 "das Wohnung"（冠词一族，v_0 == 1）。
    Injection(
        error_class="artikel",
        kind="signal",
        wrong="das Wohnung besichtigen",
        right="die Wohnung besichtigen",
        expected_count=1,
    ),
    Injection(
        error_class="praeposition_kollokation",
        kind="probe",
        wrong="über Ihre 2-Zimmer-Wohnung",
        right="für Ihre 2-Zimmer-Wohnung",
        expected_count=1,
    ),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Ich arbeiten als", right="Ich arbeite als", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="als ingenieur", right="als Ingenieur", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Wann können ich", right="Wann kann ich", expected_count=1),
]

_L4_CLEAN: str = (
    "Liebe Frau Schmidt,\n\nich kann heute leider nicht zum Kurs kommen, weil ich hohes Fieber habe. Ich bleibe bis "
    "Mittwoch im Bett. Können Sie mir bitte die Hausaufgaben per E-Mail schicken?\n\nHerzliche Grüße\nMaria"
)

_L4_INJECTIONS: list[Injection] = [
    # signal：复数四格宾语 "die Hausaufgaben" 被写成三格形 "den Hausaufgaben"（v_0 == 1）。
    Injection(error_class="artikel", kind="signal", wrong="den Hausaufgaben", right="die Hausaufgaben", expected_count=1),
    Injection(
        error_class="nebensatz_wortstellung",
        kind="probe",
        wrong="weil ich habe hohes Fieber",
        right="weil ich hohes Fieber habe",
        expected_count=1,
    ),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="ich können heute", right="ich kann heute", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Ich bleiben bis", right="Ich bleibe bis", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="zum kurs kommen", right="zum Kurs kommen", expected_count=1),
]

_L5_CLEAN: str = (
    "Lieber Michael,\n\nich ziehe am Samstag um 10 Uhr in meine neue Wohnung um. Hast du Zeit und kannst mir beim "
    "Tragen helfen? Nach dem Umzug lade ich dich zum Pizzaessen ein.\n\nViele Grüße\nTom"
)

_L5_INJECTIONS: list[Injection] = [
    # signal：nach 支配三格，"Nach dem Umzug" 被写成 "Nach den Umzug"（v_0 == 1）。
    Injection(error_class="kasus", kind="signal", wrong="Nach den Umzug", right="Nach dem Umzug", expected_count=1),
    Injection(error_class="artikel_genus", kind="probe", wrong="in meinen neue", right="in meine neue", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="ich ziehen am", right="ich ziehe am", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="und können mir", right="und kannst mir", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="neue wohnung", right="neue Wohnung", expected_count=1),
]

_L6_CLEAN: str = (
    "Liebe Sarah,\n\nes tut mir leid, aber ich muss am Freitag länger arbeiten und kann nicht kommen. "
    "Passt es dir vielleicht am Sonntag um 15 Uhr im Café Central?\n\nLiebe Grüße\nJulia"
)

_L6_INJECTIONS: list[Injection] = [
    # signal：für 支配四格，"am Sonntag" 的约期位被写坏成 "für dem Sonntag"（v_0 == 1）。
    Injection(error_class="kasus", kind="signal", wrong="für dem Sonntag", right="am Sonntag", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="ich müssen am", right="ich muss am", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="und können nicht", right="und kann nicht", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="am freitag", right="am Freitag", expected_count=1),
]

_L7_CLEAN: str = (
    "Sehr geehrte Damen und Herren,\n\nich möchte ein Doppelzimmer vom 15. bis 18. August reservieren. "
    "Ist das Frühstück im Preis enthalten und haben Sie einen Parkplatz für unser Auto?\n\n"
    "Mit freundlichen Grüßen\nStefan Müller"
)

_L7_INJECTIONS: list[Injection] = [
    # signal：für 支配四格，"für unser Auto" 的冠词被写坏成 "für unseren Auto"（v_0 == 1）。
    Injection(error_class="kasus", kind="signal", wrong="für unseren Auto", right="für unser Auto", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="ich möchten ein", right="ich möchte ein", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Sind das Frühstück", right="Ist das Frühstück", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="einen parkplatz", right="einen Parkplatz", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="im preis", right="im Preis", expected_count=1),
]

_L8_CLEAN: str = (
    "Sehr geehrte Damen und Herren,\n\nich habe gerade den A1-Kurs abgeschlossen und möchte nun A2 lernen. "
    "Wann beginnt der nächste A2-Abendkurs und wie viel kostet die Anmeldung?\n\nMit besten Grüßen\nElena Weber"
)

_L8_INJECTIONS: list[Injection] = [
    # signal：四格宾语 "die Anmeldung"（词典性别 Fem）被换成中性冠词 "das Anmeldung"（v_0 == 1）。
    Injection(error_class="artikel", kind="signal", wrong="das Anmeldung", right="die Anmeldung", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="ich haben gerade", right="ich habe gerade", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="möchten nun A2", right="möchte nun A2", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Wann beginnen der", right="Wann beginnt der", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="a1-kurs", right="A1-Kurs", expected_count=1),
]

_L9_CLEAN: str = (
    "Sehr geehrte Damen und Herren,\n\ngestern Abend habe ich an Tisch 4 gegessen und meine schwarze Tasche "
    "vergessen. Darin sind meine Hausschlüssel. Haben Sie die Tasche gefunden und wann kann ich sie abholen?\n\n"
    "Mit freundlichen Grüßen\nKlaus Braun"
)

_L9_INJECTIONS: list[Injection] = [
    # signal：四格宾语 "meine schwarze Tasche" 的冠词被写成三格形 "meiner"（v_0 == 1）。
    Injection(
        error_class="artikel",
        kind="signal",
        wrong="meiner schwarze Tasche",
        right="meine schwarze Tasche",
        expected_count=1,
    ),
    Injection(
        error_class="nomen_grossschreibung",
        kind="probe",
        wrong="meine hausschlüssel",
        right="meine Hausschlüssel",
        expected_count=1,
    ),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="an tisch 4", right="an Tisch 4", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="wann können ich sie", right="wann kann ich sie", expected_count=1),
]

_L10_CLEAN: str = (
    "Lieber Markus,\n\nich gratuliere dir ganz herzlich zum Geburtstag! Ich wünsche dir viel Gesundheit, Glück "
    "und Erfolg. Trinken wir heute in der Mittagspause zusammen einen Kaffee?\n\nBeste Grüße\nDaniel"
)

_L10_INJECTIONS: list[Injection] = [
    # signal：固定搭配 gratulieren zu 要求三格，"zum Geburtstag" 被拆写坏成 "zu den Geburtstag"
    # （搭配源 ⇒ 检出规则名为 praeposition，v_0 == 1）。
    Injection(error_class="praeposition", kind="signal", wrong="zu den Geburtstag", right="zum Geburtstag", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="ich gratulieren dir", right="ich gratuliere dir", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Ich wünschen dir", right="Ich wünsche dir", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="der mittagspause", right="der Mittagspause", expected_count=1),
]

# ── 散文 10 篇（底本 = OFFICIAL_CORPUS 前 10 篇非书信体课文，逐字复制）──────────────────

_P1_CLEAN: str = (
    "Jeden Samstag gibt es einen großen Wochenmarkt auf dem Marktplatz vor dem Rathaus. "
    "Die Menschen kaufen dort frisches Obst, Gemüse, Brot und Käse. "
    "Frau Müller kauft heute zwei Kilo Äpfel und ein Pfund Tomaten. "
    "Die Äpfel schmecken süß und sind nicht teuer. "
    "Der Verkäufer ist sehr freundlich und wünscht ein schönes Wochenende."
)

_P1_INJECTIONS: list[Injection] = [
    # signal：中性名词 "Pfund" 的冠词被写成阴性形式 "eine"（冠词一族，v_0 == 1）。
    Injection(error_class="artikel", kind="signal", wrong="eine Pfund Tomaten", right="ein Pfund Tomaten", expected_count=1),
    Injection(error_class="artikel_genus", kind="probe", wrong="auf der Marktplatz", right="auf dem Marktplatz", expected_count=1),
    Injection(
        error_class="nomen_grossschreibung",
        kind="probe",
        wrong="großen wochenmarkt",
        right="großen Wochenmarkt",
        expected_count=1,
    ),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Der Verkäufer sind", right="Der Verkäufer ist", expected_count=1),
]

_P2_CLEAN: str = (
    "Ich besuche seit drei Wochen einen Deutschkurs an der Volkshochschule. "
    "Der Unterricht beginnt jeden Dienstag und Donnerstag um achtzehn Uhr. "
    "In meiner Gruppe lernen zwölf Personen aus verschiedenen Ländern. "
    "Unser Lehrer heißt Herr Wagner. "
    "Wir machen viele Grammatikübungen und sprechen zusammen Deutsch. "
    "Das Lernen macht mir großen Spaß."
)

_P2_INJECTIONS: list[Injection] = [
    # signal：四格宾语 "einen Deutschkurs" 被写成阴性冠词 "eine"（冠词一族，v_0 == 1）。
    Injection(error_class="artikel", kind="signal", wrong="eine Deutschkurs", right="einen Deutschkurs", expected_count=1),
    Injection(error_class="artikel_genus", kind="probe", wrong="In meinem Gruppe", right="In meiner Gruppe", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Ich besuchen seit", right="Ich besuche seit", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="Der unterricht", right="Der Unterricht", expected_count=1),
]

_P3_CLEAN: str = (
    "Letztes Wochenende haben wir eine kurze Reise nach München gemacht. "
    "Am Samstagvormittag sind wir durch den Englischen Garten spaziert und haben den Surfern auf der Eisbachwelle zugeschaut. "
    "Danach besuchten wir den Marienplatz, um das berühmte Glockenspiel am Neuen Rathaus zu sehen. "
    "Am Nachmittag waren wir im Deutschen Museum, weil uns Technik und Wissenschaft sehr interessieren. "
    "Das Wetter war sonnig, und die bayerische Küche im Biergarten hat hervorragend geschmeckt."
)

_P3_INJECTIONS: list[Injection] = [
    # signal：durch 支配四格，"durch den Englischen Garten" 被写成三格形 "durch dem …"（v_0 == 1）。
    Injection(
        error_class="kasus",
        kind="signal",
        wrong="durch dem Englischen Garten",
        right="durch den Englischen Garten",
        expected_count=1,
    ),
    Injection(
        error_class="praeposition_kollokation",
        kind="probe",
        wrong="Reise in München",
        right="Reise nach München",
        expected_count=1,
    ),
    Injection(error_class="artikel_genus", kind="probe", wrong="auf dem Eisbachwelle", right="auf der Eisbachwelle", expected_count=1),
    Injection(
        error_class="nebensatz_wortstellung",
        kind="probe",
        wrong="uns interessieren Technik und Wissenschaft sehr",
        right="uns Technik und Wissenschaft sehr interessieren",
        expected_count=1,
    ),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="im biergarten", right="im Biergarten", expected_count=1),
]

_P4_CLEAN: str = (
    "Für viele Studienanfänger in Deutschland ist das Studentenwohnheim die erste Wahl. "
    "Der entscheidende Vorteil liegt in der günstigen Warmmiete, da Strom, Heizung und Internet bereits im Preis enthalten sind. "
    "Zudem knüpft man in einer Wohngemeinschaft schnell neue Kontakte mit Kommilitonen aus aller Welt. "
    "Allerdings bringt das Zusammenleben auf engem Raum auch Herausforderungen mit sich. "
    "Da Küche und Bad oft geteilt werden müssen, sind feste Putzpläne und gegenseitige Rücksichtnahme unverzichtbar. "
    "Wer viel Ruhe zum Lernen und ungestörte Privatsphäre sucht, entscheidet sich nach einigen Semestern häufig für eine eigene kleine Wohnung."
)

_P4_INJECTIONS: list[Injection] = [
    # signal：固定搭配 sich entscheiden für 要求四格，"für eine eigene kleine Wohnung" 的冠词
    # 被写成三格形 "für einer …"（搭配源 ⇒ 规则名 praeposition，v_0 == 1）。
    Injection(
        error_class="praeposition",
        kind="signal",
        wrong="für einer eigene kleine Wohnung",
        right="für eine eigene kleine Wohnung",
        expected_count=1,
    ),
    Injection(
        error_class="artikel_genus",
        kind="probe",
        wrong="in dem günstigen Warmmiete",
        right="in der günstigen Warmmiete",
        expected_count=1,
    ),
    Injection(
        error_class="artikel_genus",
        kind="probe",
        wrong="in einem Wohngemeinschaft",
        right="in einer Wohngemeinschaft",
        expected_count=1,
    ),
    Injection(
        error_class="nebensatz_wortstellung",
        kind="probe",
        wrong="im Preis sind enthalten",
        right="im Preis enthalten sind",
        expected_count=1,
    ),
    Injection(
        error_class="nomen_grossschreibung",
        kind="probe",
        wrong="das studentenwohnheim",
        right="das Studentenwohnheim",
        expected_count=1,
    ),
    Injection(
        error_class="praeposition_kollokation",
        kind="probe",
        wrong="Kontakte für Kommilitonen",
        right="Kontakte mit Kommilitonen",
        expected_count=1,
    ),
]

_P5_CLEAN: str = (
    "Das Arbeiten von zu Hause aus hat in den vergangenen Jahren stark an Bedeutung gewonnen. "
    "Viele Arbeitnehmer schätzen die Möglichkeit, ihren Tagesablauf flexibler zu gestalten und den täglichen Weg zur Arbeit im Berufsverkehr zu vermeiden. "
    "Studien belegen, dass Mitarbeiter im Homeoffice oft konzentrierter arbeiten können, sofern ein ruhiger Arbeitsplatz vorhanden ist. "
    "Gleichzeitig erfordert die Heimarbeit ein hohes Maß an Selbstdisziplin. "
    "Es fällt manchen Beschäftigten schwer, nach Feierabend abzuschalten und Berufliches von Privatem klar zu trennen. "
    "Aus diesem Grund etablieren viele moderne Unternehmen hybride Modelle mit zwei bis drei Präsenztagen pro Woche."
)

_P5_INJECTIONS: list[Injection] = [
    # signal：四格宾语 "die Möglichkeit"（词典性别 Fem）被换成中性冠词 "das Möglichkeit"（v_0 == 1）。
    Injection(error_class="artikel", kind="signal", wrong="das Möglichkeit", right="die Möglichkeit", expected_count=1),
    Injection(
        error_class="nebensatz_wortstellung",
        kind="probe",
        wrong="oft konzentrierter können arbeiten",
        right="oft konzentrierter arbeiten können",
        expected_count=1,
    ),
    Injection(
        error_class="verb_kongruenz",
        kind="probe",
        wrong="erfordern die Heimarbeit",
        right="erfordert die Heimarbeit",
        expected_count=1,
    ),
    Injection(error_class="praeposition_kollokation", kind="probe", wrong="mit Privatem", right="von Privatem", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="an selbstdisziplin", right="an Selbstdisziplin", expected_count=1),
]

_P6_CLEAN: str = (
    "Das duale Ausbildungssystem gilt als eine der tragenden Säulen der deutschen Wirtschaft. "
    "Auszubildende lernen dabei sowohl die theoretischen Grundlagen in der Berufsschule als auch die praktische Arbeit direkt im Betrieb. "
    "Dieses Modell dauert in der Regel zwischen zwei und dreieinhalb Jahren und wird mit einer monatlichen Ausbildungsvergütung vergütet. "
    "Durch die enge Verknüpfung von Fachwissen und Betriebspraxis sind die Absolventen nach ihrem Abschluss sofort voll einsetzbar. "
    "Internationale Bildungsexperten loben das deutsche System regelmäßig, da es maßgeblich dazu beiträgt, die Jugendarbeitslosigkeit "
    "im Vergleich zu anderen europäischen Ländern niedrig zu halten."
)

_P6_INJECTIONS: list[Injection] = [
    # signal：nach 支配三格，"nach ihrem Abschluss" 被写成四格形 "nach ihren …"（v_0 == 1）。
    Injection(error_class="kasus", kind="signal", wrong="nach ihren Abschluss", right="nach ihrem Abschluss", expected_count=1),
    Injection(error_class="artikel_genus", kind="probe", wrong="in dem Regel", right="in der Regel", expected_count=1),
    Injection(error_class="artikel_genus", kind="probe", wrong="in dem Berufsschule", right="in der Berufsschule", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Dieses Modell dauern", right="Dieses Modell dauert", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="deutschen wirtschaft", right="deutschen Wirtschaft", expected_count=1),
]

_P7_CLEAN: str = (
    "Der Einsatz von Algorithmen des maschinellen Lernens revolutioniert gegenwärtig die medizinische Bildgebung und Frühdiagnostik. "
    "Moderne neuronale Netze sind in der Lage, radiologische Aufnahmen wie Röntgenbilder oder MRT-Scans innerhalb von Sekundenbruchteilen zu analysieren. "
    "In mehreren klinischen Studien konnte nachgewiesen werden, dass spezialisierte KI-Systeme verdächtige Gewebeveränderungen mit einer Präzision erkennen, "
    "die der erfahrener Fachärzte in nichts nachsteht. "
    "Dennoch betonen Experten weltweit, dass Algorithmen die ärztliche Expertise keineswegs ersetzen, sondern vielmehr als entlastendes Assistenzsystem fungieren sollen. "
    "Die letztendliche therapeutische Entscheidung und die ethische Verantwortung verbleiben unabdingbar in der Hand des behandelnden Mediziners."
)

_P7_INJECTIONS: list[Injection] = [
    # signal：mit 支配三格，"mit einer Präzision" 的冠词被写成四格形 "mit eine …"（v_0 == 1）。
    Injection(error_class="kasus", kind="signal", wrong="mit eine Präzision", right="mit einer Präzision", expected_count=1),
    Injection(error_class="artikel_genus", kind="probe", wrong="in dem Hand", right="in der Hand", expected_count=1),
    Injection(error_class="artikel_genus", kind="probe", wrong="in dem Lage", right="in der Lage", expected_count=1),
    Injection(
        error_class="nebensatz_wortstellung",
        kind="probe",
        wrong="Algorithmen ersetzen die ärztliche Expertise keineswegs",
        right="Algorithmen die ärztliche Expertise keineswegs ersetzen",
        expected_count=1,
    ),
    Injection(
        error_class="nomen_grossschreibung",
        kind="probe",
        wrong="gewebeveränderungen",
        right="Gewebeveränderungen",
        expected_count=1,
    ),
    Injection(
        error_class="verb_kongruenz",
        kind="probe",
        wrong="revolutionieren gegenwärtig",
        right="revolutioniert gegenwärtig",
        expected_count=1,
    ),
]

_P8_CLEAN: str = (
    "Die Umstellung der nationalen Energieversorgung auf erneuerbare Quellen bildet das Herzstück der deutschen Klimaschutzstrategie. "
    "Bis zum Jahr 2030 soll der Anteil von Windkraft und Solarenergie am Bruttostromverbrauch auf mindestens achtzig Prozent gesteigert werden. "
    "Um dieses ambitionierte Ziel zu erreichen, bedarf es jedoch nicht nur der Errichtung neuer Windparks auf See und an Land, "
    "sondern vor allem des massiven Ausbaus der Hochspannungsübertragungsnetze von Nord- nach Süddeutschland. "
    "Darüber hinaus gewinnen innovative Speichertechnologien wie grüner Wasserstoff und moderne Batteriespeicher rasant an Bedeutung, "
    "um witterungsbedingte Schwankungen in der Stromproduktion zuverlässig auszugleichen."
)

_P8_INJECTIONS: list[Injection] = [
    # signal：句首主语 "Die Umstellung"（词典性别 Fem）被写成三格冠词 "Dem Umstellung"（v_0 == 1）。
    Injection(error_class="artikel", kind="signal", wrong="Dem Umstellung", right="Die Umstellung", expected_count=1),
    Injection(
        error_class="artikel_genus",
        kind="probe",
        wrong="in dem Stromproduktion",
        right="in der Stromproduktion",
        expected_count=1,
    ),
    Injection(error_class="praeposition_kollokation", kind="probe", wrong="in Bedeutung", right="an Bedeutung", expected_count=1),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="Quellen bilden das", right="Quellen bildet das", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="das herzstück", right="das Herzstück", expected_count=1),
]

_P9_CLEAN: str = (
    "Die weltweite Kontamination der Meere durch mikroskopisch kleine Kunststoffpartikel, sogenanntes Mikroplastik, "
    "stellt eine erhebliche Bedrohung für marine Organismen dar. "
    "Diese Partikel mit einem Durchmesser von weniger als fünf Millimetern entstehen vorwiegend durch die Zersetzung größerer Plastikabfälle "
    "infolge von UV-Strahlung und Wellenbewegung. "
    "Aufgrund ihrer winzigen Beschaffenheit werden sie von Plankton, Fischen und Seevögeln mit natürlicher Nahrung verwechselt und unbemerkt aufgenommen. "
    "In den Verdauungstrakten der Tiere können die unlöslichen Kunststoffteilchen schwere Entzündungen und Scheinsättigung hervorrufen. "
    "Besonders besorgniserregend ist die Tatsache, dass an den porösen Oberflächen der Partikel toxische Schadstoffe anhaften, "
    "die sich über die Nahrungskette bis zum Menschen anreichern können."
)

_P9_INJECTIONS: list[Injection] = [
    # signal：mit 支配三格，"mit einem Durchmesser" 的冠词被写成四格形 "mit einen …"（v_0 == 1）。
    Injection(error_class="kasus", kind="signal", wrong="mit einen Durchmesser", right="mit einem Durchmesser", expected_count=1),
    Injection(
        error_class="praeposition_kollokation",
        kind="probe",
        wrong="Bedrohung auf marine",
        right="Bedrohung für marine",
        expected_count=1,
    ),
    Injection(
        error_class="nebensatz_wortstellung",
        kind="probe",
        wrong="der Partikel anhaften toxische Schadstoffe",
        right="der Partikel toxische Schadstoffe anhaften",
        expected_count=1,
    ),
    Injection(
        error_class="verb_kongruenz",
        kind="probe",
        wrong="stellen eine erhebliche",
        right="stellt eine erhebliche",
        expected_count=1,
    ),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="die nahrungskette", right="die Nahrungskette", expected_count=1),
]

_P10_CLEAN: str = (
    "Deutsche Hochschulen erfreuen sich bei ausländischen Studierenden und Nachwuchswissenschaftlern weltweit wachsender Beliebtheit. "
    "Um im globalen Wettbewerb um die klügsten Köpfe wettbewerbsfähig zu bleiben, haben viele Universitäten in den vergangenen Jahren "
    "ihr Angebot an englischsprachigen Masterstudiengängen drastisch ausgebaut. "
    "Dieser Internationalisierungsschub fördert nicht nur den wissenschaftlichen Diskurs über Ländergrenzen hinweg, "
    "sondern bereichert auch das studentische Campusleben durch interkulturelle Vielfalt. "
    "Gleichwohl betonen Hochschulrektoren, dass das frühzeitige Erlernen der deutschen Sprache für eine nachhaltige soziale Integration "
    "und den späteren Einstieg in den hiesigen Arbeitsmarkt von entscheidender Bedeutung bleibt."
)

_P10_INJECTIONS: list[Injection] = [
    # signal：für 支配四格，"für eine nachhaltige soziale Integration" 的冠词被写成三格形
    # "für einer …"（v_0 == 1）。
    Injection(
        error_class="kasus",
        kind="signal",
        wrong="für einer nachhaltige soziale Integration",
        right="für eine nachhaltige soziale Integration",
        expected_count=1,
    ),
    Injection(
        error_class="artikel_genus",
        kind="probe",
        wrong="in der hiesigen Arbeitsmarkt",
        right="in den hiesigen Arbeitsmarkt",
        expected_count=1,
    ),
    Injection(error_class="verb_kongruenz", kind="probe", wrong="schub fördern nicht", right="schub fördert nicht", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="campusleben durch", right="Campusleben durch", expected_count=1),
    Injection(error_class="nomen_grossschreibung", kind="probe", wrong="hochschulrektoren", right="Hochschulrektoren", expected_count=1),
]

# ── 冻结的种子集：20 篇（书信 10 + 散文 10），每篇 ≥3 处注入 ────────────────────────────

SEED_CASES: list[SeedCase] = [
    SeedCase(
        id="letter_01_party_einladung",
        text=_inject(_L1_CLEAN, _L1_INJECTIONS),
        clean_text=_L1_CLEAN,
        injections=_L1_INJECTIONS,
    ),
    SeedCase(
        id="letter_02_termin_absagen",
        text=_inject(_L2_CLEAN, _L2_INJECTIONS),
        clean_text=_L2_CLEAN,
        injections=_L2_INJECTIONS,
    ),
    SeedCase(
        id="letter_03_wohnung_besichtigung",
        text=_inject(_L3_CLEAN, _L3_INJECTIONS),
        clean_text=_L3_CLEAN,
        injections=_L3_INJECTIONS,
    ),
    SeedCase(
        id="letter_04_krankmeldung_kurs",
        text=_inject(_L4_CLEAN, _L4_INJECTIONS),
        clean_text=_L4_CLEAN,
        injections=_L4_INJECTIONS,
    ),
    SeedCase(
        id="letter_05_hilfe_umzug",
        text=_inject(_L5_CLEAN, _L5_INJECTIONS),
        clean_text=_L5_CLEAN,
        injections=_L5_INJECTIONS,
    ),
    SeedCase(
        id="letter_06_treffen_verschieben",
        text=_inject(_L6_CLEAN, _L6_INJECTIONS),
        clean_text=_L6_CLEAN,
        injections=_L6_INJECTIONS,
    ),
    SeedCase(
        id="letter_07_hotelbuchung_anfrage",
        text=_inject(_L7_CLEAN, _L7_INJECTIONS),
        clean_text=_L7_CLEAN,
        injections=_L7_INJECTIONS,
    ),
    SeedCase(
        id="letter_08_deutschkurs_auskunft",
        text=_inject(_L8_CLEAN, _L8_INJECTIONS),
        clean_text=_L8_CLEAN,
        injections=_L8_INJECTIONS,
    ),
    SeedCase(
        id="letter_09_fundsache_anfrage",
        text=_inject(_L9_CLEAN, _L9_INJECTIONS),
        clean_text=_L9_CLEAN,
        injections=_L9_INJECTIONS,
    ),
    SeedCase(
        id="letter_10_geburtstagsglueckwunsch",
        text=_inject(_L10_CLEAN, _L10_INJECTIONS),
        clean_text=_L10_CLEAN,
        injections=_L10_INJECTIONS,
    ),
    SeedCase(
        id="prose_01_wochenmarkt",
        text=_inject(_P1_CLEAN, _P1_INJECTIONS),
        clean_text=_P1_CLEAN,
        injections=_P1_INJECTIONS,
    ),
    SeedCase(
        id="prose_02_deutschkurs_vhs",
        text=_inject(_P2_CLEAN, _P2_INJECTIONS),
        clean_text=_P2_CLEAN,
        injections=_P2_INJECTIONS,
    ),
    SeedCase(
        id="prose_03_wochenende_muenchen",
        text=_inject(_P3_CLEAN, _P3_INJECTIONS),
        clean_text=_P3_CLEAN,
        injections=_P3_INJECTIONS,
    ),
    SeedCase(
        id="prose_04_studentenwohnheim",
        text=_inject(_P4_CLEAN, _P4_INJECTIONS),
        clean_text=_P4_CLEAN,
        injections=_P4_INJECTIONS,
    ),
    SeedCase(
        id="prose_05_homeoffice",
        text=_inject(_P5_CLEAN, _P5_INJECTIONS),
        clean_text=_P5_CLEAN,
        injections=_P5_INJECTIONS,
    ),
    SeedCase(
        id="prose_06_duale_ausbildung",
        text=_inject(_P6_CLEAN, _P6_INJECTIONS),
        clean_text=_P6_CLEAN,
        injections=_P6_INJECTIONS,
    ),
    SeedCase(
        id="prose_07_ki_diagnostik",
        text=_inject(_P7_CLEAN, _P7_INJECTIONS),
        clean_text=_P7_CLEAN,
        injections=_P7_INJECTIONS,
    ),
    SeedCase(
        id="prose_08_energiewende",
        text=_inject(_P8_CLEAN, _P8_INJECTIONS),
        clean_text=_P8_CLEAN,
        injections=_P8_INJECTIONS,
    ),
    SeedCase(
        id="prose_09_mikroplastik",
        text=_inject(_P9_CLEAN, _P9_INJECTIONS),
        clean_text=_P9_CLEAN,
        injections=_P9_INJECTIONS,
    ),
    SeedCase(
        id="prose_10_hochschulbildung",
        text=_inject(_P10_CLEAN, _P10_INJECTIONS),
        clean_text=_P10_CLEAN,
        injections=_P10_INJECTIONS,
    ),
]
