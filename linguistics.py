"""
DeLector - German Morphology & Linguistics Core Engine (v3.4.0)
Goethe A1-C1 Irregular Verbs Stammformen & German Compound Noun (Komposita) Splitter.
100% Python standard library, zero external dependencies, O(1) lookup latency.
"""
from typing import Optional, Dict, Any, List, Tuple

# Import local Goethe core dictionary for compound base elements & CEFR lookup
try:
    from core_dict import CORE_VOCAB_DB, lookup_core_vocab
except ImportError:
    CORE_VOCAB_DB = {}
    lookup_core_vocab = lambda w: None


# ==============================================================================
# 1. Goethe A1-C1 Irregular & Strong Verbs Database (180+ Verbs)
# ==============================================================================
# Format: Infinitiv -> (Präteritum, Partizip II, Hilfsverb, Definition_zh)
IRREGULAR_VERBS: Dict[str, Tuple[str, str, str, str]] = {
    # ── Auxiliaries & Modals ──────────────────────────────────────────────────
    "sein": ("war", "gewesen", "ist", "是，存在，处于"),
    "haben": ("hatte", "gehabt", "hat", "有，拥有"),
    "werden": ("wurde", "geworden", "ist", "成为，变得；将要(助动词)"),
    "können": ("konnte", "gekonnt", "hat", "能够，可以，会(情态动词)"),
    "müssen": ("musste", "gemusst", "hat", "必须，不得不(情态动词)"),
    "wollen": ("wollte", "gewollt", "hat", "想要，打算(情态动词)"),
    "dürfen": ("durfte", "gedurft", "hat", "允许，可以(情态动词)"),
    "sollen": ("sollte", "gesollt", "hat", "应当，应该(情态动词)"),
    "mögen": ("mochte", "gemocht", "hat", "喜欢，可能(情态动词)"),
    "wissen": ("wusste", "gewusst", "hat", "知道，了解，晓得"),

    # ── Mixed Verbs (Gemischte Verben) ────────────────────────────────────────
    "brennen": ("brannte", "gebrannt", "hat", "燃烧，灼痛"),
    "verbrennen": ("verbrannte", "verbrannt", "hat", "烧毁，烧伤"),
    "kennen": ("kannte", "gekannt", "hat", "认识，熟悉"),
    "erkennen": ("erkannte", "erkannt", "hat", "认出，辨认，认识到"),
    "anerkennen": ("erkannte an", "anerkannt", "hat", "承认，认可"),
    "nennen": ("nannte", "genannt", "hat", "称呼，命名，提及"),
    "benennen": ("benannte", "benannt", "hat", "给...命名，指派"),
    "rennen": ("rannte", "gerannt", "ist", "奔跑，快跑，猛冲"),
    "senden": ("sandte", "gesandt", "hat", "发送，寄送，派遣"),
    "zusenden": ("sandte zu", "zugesandt", "hat", "寄给，发送给"),
    "absenden": ("sandte ab", "abgesandt", "hat", "寄发，发出"),
    "wenden": ("wandte", "gewandt", "hat", "翻转；求助，转向(sich an)"),
    "anwenden": ("wandte an", "angewandt", "hat", "应用，使用"),
    "verwenden": ("verwandte", "verwandt", "hat", "使用，利用，花费"),
    "abwenden": ("wandte ab", "abgewandt", "hat", "转开；防止，避开"),
    "bringen": ("brachte", "gebracht", "hat", "带来，送去，拿来"),
    "beibringen": ("brachte bei", "beigebracht", "hat", "教会，传授，提供"),
    "anbringen": ("brachte an", "angebracht", "hat", "安装，提出，安置"),
    "verbringen": ("verbrachte", "verbracht", "hat", "度过(时光)，花费"),
    "mitbringen": ("brachte mit", "mitgebracht", "hat", "随身带来，携带"),
    "einbringen": ("brachte ein", "eingebracht", "hat", "带来(收益)，引入"),
    "umbringen": ("brachte um", "umgebracht", "hat", "杀害，杀死"),
    "vollbringen": ("vollbrachte", "vollbracht", "hat", "完成，实现"),
    "denken": ("dachte", "gedacht", "hat", "想，思考，认为"),
    "nachdenken": ("dachte nach", "nachgedacht", "hat", "深思，考虑(über)"),
    "überdenken": ("überdachte", "überdacht", "hat", "重新考虑，反思"),
    "bedenken": ("bedachte", "bedacht", "hat", "考虑，顾及"),
    "ausdenken": ("dachte aus", "ausgedacht", "hat", "想出，虚构(sich)"),

    # ── Ablautreihe 1: ei -> i -> i / ei -> ie -> ie ──────────────────────────
    "beißen": ("biss", "gebissen", "hat", "咬，叮"),
    "bleiben": ("blieb", "geblieben", "ist", "停留，保持，留下"),
    "bleichen": ("blich", "geblichen", "ist", "褪色，变白"),
    "erbleichen": ("erblich", "erblichen", "ist", "脸色发白，去世"),
    "gedeihen": ("gedieh", "gediehen", "ist", "茁壮成长，繁荣"),
    "gleichen": ("glich", "geglichen", "hat", "相像，类似(Dativ)"),
    "vergleichen": ("verglich", "verglichen", "hat", "比较，对比(mit)"),
    "ausgleichen": ("glich aus", "ausgeglichen", "hat", "平衡，补偿，消除"),
    "gleiten": ("glitt", "geglitten", "ist", "滑行，滑落"),
    "abgleiten": ("glitt ab", "abgeglitten", "ist", "滑落，偏离"),
    "greifen": ("griff", "gegriffen", "hat", "抓住，握住，抓取"),
    "angreifen": ("griff an", "angegriffen", "hat", "攻击，进攻"),
    "begreifen": ("begriff", "begriffen", "hat", "理解，领会"),
    "ergreifen": ("ergriff", "ergriffen", "hat", "抓住(机会)，采取(措施)"),
    "zugreifen": ("griff zu", "zugegriffen", "hat", "动手取用，抓住(机会)"),
    "durchgreifen": ("griff durch", "durchgegriffen", "hat", "采取严厉措施"),
    "kneifen": ("kniff", "gekniffen", "hat", "捏，夹，退缩"),
    "leihen": ("lieh", "geliehen", "hat", "借出，借入(von/an)"),
    "ausleihen": ("lieh aus", "ausgeliehen", "hat", "借出，借来"),
    "verleihen": ("verlieh", "verliehen", "hat", "出借；授予，赋予"),
    "meiden": ("mied", "gemieden", "hat", "避开，躲避"),
    "vermeiden": ("vermied", "vermieden", "hat", "避免，防止"),
    "pfeifen": ("pfiff", "gepfiffen", "hat", "吹口哨，吹哨"),
    "anpfeifen": ("pfiff an", "angepfiffen", "hat", "鸣笛开赛；斥责"),
    "preisen": ("pries", "gepriesen", "hat", "赞美，颂扬"),
    "anpreisen": ("pries an", "angepriesen", "hat", "竭力赞扬，夸耀"),
    "reiben": ("rieb", "gerieben", "hat", "摩擦，研磨，擦拭"),
    "einreiben": ("rieb ein", "eingerieben", "hat", "涂抹，揉擦"),
    "reißen": ("riss", "gerissen", "hat/ist", "撕破，拉扯；断裂"),
    "zerreißen": ("zerriss", "zerrissen", "hat/ist", "撕碎，扯断"),
    "abreißen": ("riss ab", "abgerissen", "hat/ist", "拆毁，中断"),
    "aufreißen": ("riss auf", "aufgerissen", "hat", "撕开，敞开"),
    "mitreißen": ("riss mit", "mitgerissen", "hat", "吸引，带动，冲走"),
    "reiten": ("ritt", "geritten", "ist/hat", "骑马"),
    "scheiden": ("schied", "geschieden", "hat/ist", "使分离，判决离婚；离去"),
    "ausscheiden": ("schied aus", "ausgeschieden", "ist/hat", "退赛，退出，离职；排泄"),
    "entscheiden": ("entschied", "entschieden", "hat", "决定，判决"),
    "unterscheiden": ("unterschied", "unterschieden", "hat", "区别，辨别(von)"),
    "scheinen": ("schien", "geschienen", "hat", "照耀，发光；似乎，看来"),
    "erscheinen": ("erschien", "erschienen", "ist", "出现，出版，显得"),
    "schleichen": ("schlich", "geschlichen", "ist", "潜行，溜走，悄悄走"),
    "einschleichen": ("schlich ein", "eingeschlichen", "ist", "潜入，潜伏(sich)"),
    "schleifen": ("schliff", "geschliffen", "hat", "打磨，研磨，磨快"),
    "schmeißen": ("schmiss", "geschmissen", "hat", "扔，摔，抛"),
    "hinschmeißen": ("schmiss hin", "hingeschmissen", "hat", "扔下，放弃"),
    "schneiden": ("schnitt", "geschnitten", "hat", "切，剪，割"),
    "abschneiden": ("schnitt ab", "abgeschnitten", "hat", "剪下，截断；取得成绩"),
    "ausschneiden": ("schnitt aus", "ausgeschnitten", "hat", "剪出，剪下"),
    "zuschneiden": ("schnitt zu", "zugeschnitten", "hat", "裁剪，为...量身定制"),
    "schreiben": ("schrieb", "geschrieben", "hat", "写，书写"),
    "anschreiben": ("schrieb an", "angeschrieben", "hat", "写信给，记账"),
    "aufschreiben": ("schrieb auf", "aufgeschrieben", "hat", "记下，写下"),
    "beschreiben": ("beschrieb", "beschrieben", "hat", "描述，描绘"),
    "einschreiben": ("schrieb ein", "eingeschrieben", "hat", "登记，注册(sich)"),
    "unterschreiben": ("unterschrieb", "unterschrieben", "hat", "签字，签署"),
    "vorschreiben": ("schrieb vor", "vorgeschrieben", "hat", "规定，指令"),
    "mitschreiben": ("schrieb mit", "mitgeschrieben", "hat", "做笔记，随堂记录"),
    "schreien": ("schrie", "geschrien", "hat", "叫喊，大叫"),
    "anschreien": ("schrie an", "angeschrien", "hat", "对...大吼"),
    "schreiten": ("schritt", "geschritten", "ist", "迈步，跨步，着手(zu)"),
    "fortschreiten": ("schritt fort", "fortgeschritten", "ist", "进步，推进"),
    "überschreiten": ("überschritt", "überschritten", "hat", "跨越，逾越，超过"),
    "schweigen": ("schwieg", "geschwiegen", "hat", "沉默，缄默，闭口不言"),
    "verschweigen": ("verschwieg", "verschwiegen", "hat", "隐瞒，不透露"),
    "speien": ("spie", "gespien", "hat", "吐出，喷出"),
    "steigen": ("stieg", "gestiegen", "ist", "上升，攀登，上涨"),
    "ansteigen": ("stieg an", "angestiegen", "ist", "攀升，增长"),
    "aussteigen": ("stieg aus", "ausgestiegen", "ist", "下车，退出"),
    "einsteigen": ("stieg ein", "eingestiegen", "ist", "上车，参与"),
    "umsteigen": ("stieg um", "umgestiegen", "ist", "换乘，转车"),
    "absteigen": ("stieg ab", "abgestiegen", "ist", "下车，下榻，降级"),
    "hinaufsteigen": ("stieg hinauf", "hinaufgestiegen", "ist", "登上，攀上去"),
    "streichen": ("strich", "gestrichen", "hat", "涂刷，划掉，删除"),
    "unterstreichen": ("unterstrich", "unterstrichen", "hat", "强调，画底线"),
    "abstreichen": ("strich ab", "abgestrichen", "hat", "勾掉，抹去"),
    "streiten": ("stritt", "gestritten", "hat", "争论，争吵(über/um)"),
    "abstreiten": ("stritt ab", "abgestritten", "hat", "否认，抵赖"),
    "treiben": ("trieb", "getrieben", "hat/ist", "驱赶，推动；从事(Sport)"),
    "antreiben": ("trieb an", "angetrieben", "hat", "驱动，鞭策，推动"),
    "betreiben": ("betrieb", "betrieben", "hat", "经营，从事，运行"),
    "übertreiben": ("übertrieb", "übertrieben", "hat", "夸张，夸大"),
    "vertreiben": ("vertrieb", "vertrieben", "hat", "驱逐，推销，消磨(Zeit)"),
    "weisen": ("wies", "gewiesen", "hat", "指示，指明，展现"),
    "anweisen": ("wies an", "angewiesen", "hat", "指导，指定，汇出(款项)"),
    "aufweisen": ("wies auf", "aufgewiesen", "hat", "呈现，具有，显示出"),
    "beweisen": ("bewies", "bewiesen", "hat", "证明，证实"),
    "hinweisen": ("wies hin", "hingewiesen", "hat", "指出，提示(auf)"),
    "nachweisen": ("wies nach", "nachgewiesen", "hat", "证实，查明，提供证明"),
    "überweisen": ("überwies", "überwiesen", "hat", "转账，转诊"),
    "zurückweisen": ("wies zurück", "zurückgewiesen", "hat", "拒绝，驳回"),
    "verweisen": ("verwies", "verwiesen", "hat", "参照，驱逐，告诫(auf)"),
    "weichen": ("wich", "gewichen", "ist", "让步，避开，退却"),
    "ausweichen": ("wich aus", "ausgewichen", "ist", "避开，回避(Dativ)"),
    "abweichen": ("wich ab", "abgewichen", "ist", "偏离，不同于(von)"),
    "verzeihen": ("verzieh", "verziehen", "hat", "原谅，宽恕(Dativ)"),

    # ── Ablautreihe 2: ie -> o -> o / e -> o -> o / ü/au -> o -> o ─────────────
    "biegen": ("bog", "gebogen", "hat/ist", "使弯曲；拐弯"),
    "abbiegen": ("bog ab", "abgebogen", "ist", "拐弯，转弯"),
    "einbiegen": ("bog ein", "eingebogen", "ist", "拐入(街道)"),
    "verbiegen": ("verbog", "verbogen", "hat", "扭曲，弯折"),
    "bieten": ("bot", "geboten", "hat", "提供，展现，出价"),
    "anbieten": ("bot an", "angeboten", "hat", "提供，提议，供应"),
    "verbieten": ("verbot", "verboten", "hat", "禁止，不准"),
    "gebieten": ("gebot", "geboten", "hat", "命令，要求；支配"),
    "darbieten": ("bot dar", "dargeboten", "hat", "表演，呈献"),
    "fliegen": ("flog", "geflogen", "ist/hat", "飞，飞行，乘飞机"),
    "abfliegen": ("flog ab", "abgeflogen", "ist", "起飞"),
    "überfliegen": ("überflog", "überflogen", "hat", "飞越；略读，浏览"),
    "fliehen": ("floh", "geflohen", "ist", "逃跑，逃走，逃避"),
    "entfliehen": ("entfloh", "entflohen", "ist", "逃离，逃脱(Dativ)"),
    "fließen": ("floss", "geflossen", "ist", "流动，流淌"),
    "abfließen": ("floss ab", "abgeflossen", "ist", "流出，流走"),
    "einfließen": ("floss ein", "eingeflossen", "ist", "流入；汇入，融入"),
    "frieren": ("fror", "gefroren", "hat/ist", "感到寒冷；结冰"),
    "einfrieren": ("fror ein", "eingefroren", "hat/ist", "冷冻，冻结(资金)"),
    "erfrieren": ("erfror", "erfroren", "ist", "冻死，冻伤"),
    "genießen": ("genoss", "genossen", "hat", "享受，享有，品味"),
    "gießen": ("goss", "gegossen", "hat", "浇灌，倒(液体)，铸造"),
    "eingießen": ("goss ein", "eingegossen", "hat", "倒入，注入"),
    "kriechen": ("kroch", "gekrochen", "ist", "爬行，匍匐"),
    "riechen": ("roch", "gerochen", "hat", "闻到，发出气味(nach)"),
    "schieben": ("schob", "geschoben", "hat", "推，挪动，推迟"),
    "verschieben": ("verschob", "verschoben", "hat", "推迟，延期，挪动"),
    "aufschieben": ("schob auf", "aufgeschoben", "hat", "延期，拖延"),
    "schießen": ("schoss", "geschossen", "hat/ist", "射击，开枪；疾驰"),
    "erschießen": ("erschoss", "erschossen", "hat", "枪毙，击毙"),
    "abschießen": ("schoss ab", "abgeschossen", "hat", "击落，发射"),
    "schließen": ("schloss", "geschlossen", "hat", "关闭，锁上；推断"),
    "abschließen": ("schloss ab", "abgeschlossen", "hat", "锁上；完成，毕业；签订"),
    "anschließen": ("schloss an", "angeschlossen", "hat", "连接；加入(sich)"),
    "beschließen": ("beschloss", "beschlossen", "hat", "做出决定，通过决议"),
    "einschließen": ("schloss ein", "eingeschlossen", "hat", "锁入；包含，包括"),
    "ausschließen": ("schloss aus", "ausgeschlossen", "hat", "排除，开除，消除"),
    "erschließen": ("erschloss", "erschlossen", "hat", "开发，开拓，推断出"),
    "kurzschließen": ("schloss kurz", "kurzgeschlossen", "hat", "短路；直接沟通"),
    "verlieren": ("verlor", "verloren", "hat", "丢失，失去，输掉"),
    "wiegen": ("wog", "gewogen", "hat", "重量为，称重"),
    "abwägen": ("wog ab", "abgewogen", "hat", "权衡，斟酌"),
    "erwägen": ("erwog", "erwogen", "hat", "考虑，斟酌"),
    "ziehen": ("zog", "gezogen", "hat/ist", "拉，拖；迁移，搬家"),
    "anziehen": ("zog an", "angezogen", "hat", "穿衣，吸引，拧紧"),
    "ausziehen": ("zog aus", "ausgezogen", "hat/ist", "脱衣；搬出"),
    "umziehen": ("zog um", "umgezogen", "ist/hat", "搬家；换衣服(sich)"),
    "einziehen": ("zog ein", "eingezogen", "ist/hat", "搬入，入住；收回"),
    "beziehen": ("bezog", "bezogen", "hat", "入住，订购；涉及(auf)"),
    "erziehen": ("erzog", "erzogen", "hat", "教育，抚养"),
    "vorziehen": ("zog vor", "vorgezogen", "hat", "偏爱，宁可；提前"),
    "zurückziehen": ("zog zurück", "zurückgezogen", "hat/ist", "撤回，收回；隐居(sich)"),
    "vollziehen": ("vollzog", "vollzogen", "hat", "执行，实施，进行"),
    "überziehen": ("überzog", "überzogen", "hat", "套上；透支(Konto)"),
    "heben": ("hob", "gehoben", "hat", "举起，提升，升高"),
    "abheben": ("hob ab", "abgehoben", "hat/ist", "取款；起飞；显眼"),
    "aufheben": ("hob auf", "aufgehoben", "hat", "捡起；保存；废除"),
    "hervorheben": ("hob hervor", "hervorgehoben", "hat", "强调，突出"),
    "erheben": ("erhob", "erhoben", "hat", "举起，征收(税)；提出(异议)"),
    "schmelzen": ("schmolz", "geschmolzen", "ist/hat", "融化，熔化"),
    "schwellen": ("schwoll", "geschwollen", "ist", "膨胀，肿胀"),
    "anschwellen": ("schwoll an", "angeschwollen", "ist", "肿起，增大"),
    "quellen": ("quoll", "gequollen", "ist", "涌出，泡发"),
    "erlöschen": ("erlosch", "erloschen", "ist", "熄灭，失效，终止"),
    "lügen": ("log", "gelogen", "hat", "说谎，撒谎"),
    "belügen": ("belog", "belogen", "hat", "欺骗(某人)"),
    "trügen": ("trog", "getrogen", "hat", "欺骗，具有欺骗性"),
    "betrügen": ("betrog", "betrogen", "hat", "欺骗，作弊，背叛"),
    "saugen": ("sog", "gesogen", "hat", "吸，吸收，吸尘"),
    "saufen": ("soff", "gesoffen", "hat", "痛饮，暴饮(动物饮水)"),

    # ── Ablautreihe 3: i -> a -> u / i -> a -> o ───────────────────────────────
    "binden": ("band", "gebunden", "hat", "绑，系，结合，束缚"),
    "anbinden": ("band an", "angebunden", "hat", "拴住，系上"),
    "verbinden": ("verband", "verbunden", "hat", "连接，包扎，结合"),
    "unterbinden": ("unterband", "unterbunden", "hat", "阻止，制止"),
    "dringen": ("drang", "gedrungen", "ist/hat", "穿透，挤入，坚持要求(auf)"),
    "durchdringen": ("drang durch", "durchgedrungen", "ist", "渗透，穿过"),
    "eindringen": ("drang ein", "eingedrungen", "ist", "侵入，闯入"),
    "aufdrängen": ("drängte auf", "aufgedrängt", "hat", "强加于(sich)"),
    "finden": ("fand", "gefunden", "hat", "找到，发现，觉得"),
    "auffinden": ("fand auf", "aufgefunden", "hat", "寻获，找到"),
    "befinden": ("befand", "befunden", "hat", "处于，位于(sich)"),
    "erfinden": ("erfand", "erfunden", "hat", "发明，虚构"),
    "herausfinden": ("fand heraus", "herausgefunden", "hat", "查明，找出"),
    "stattfinden": ("fand statt", "stattgefunden", "hat", "举行，发生"),
    "abfinden": ("fand ab", "abgefunden", "hat", "补偿；甘心于(sich mit)"),
    "gelingen": ("gelang", "gelungen", "ist", "成功，办成(Dativ)"),
    "misslingen": ("misslang", "misslungen", "ist", "失败，未成功(Dativ)"),
    "klingen": ("klang", "geklungen", "hat", "发声，听起来"),
    "erklingen": ("erklang", "erklungen", "ist", "响起，奏响"),
    "anklingen": ("klang an", "angeklungen", "hat", "提及，隐约显露"),
    "ringen": ("rang", "gerungen", "hat", "搏斗，摔跤；竭力争取(um)"),
    "durchringen": ("rang durch", "durchgerungen", "hat", "下定决心(sich zu)"),
    "schlingen": ("schlang", "geschlungen", "hat", "缠绕；狼吞虎咽"),
    "verschlingen": ("verschlang", "verschlungen", "hat", "吞食，吞没"),
    "schwinden": ("schwand", "geschwunden", "ist", "缩减，减退"),
    "verschwinden": ("verschwand", "verschwunden", "ist", "消失，失踪"),
    "schwingen": ("schwang", "geschwungen", "hat/ist", "摆动，挥舞，震颤"),
    "singen": ("sang", "gesungen", "hat", "唱，唱歌"),
    "vorsingen": ("sang vor", "vorgesungen", "hat", "试唱，领唱"),
    "sinken": ("sank", "gesunken", "ist", "下降，下沉，降低"),
    "absinken": ("sank ab", "abgesunken", "ist", "滑落，下降"),
    "versinken": ("versank", "versunken", "ist", "下沉，沉没"),
    "springen": ("sprang", "gesprungen", "ist", "跳跃，跳，裂开"),
    "abspringen": ("sprang ab", "abgesprungen", "ist", "跳下，退出"),
    "anspringen": ("sprang an", "angesprungen", "ist", "启动(引擎)；扑向"),
    "aufspringen": ("sprang auf", "aufgesprungen", "ist", "跳起；裂开"),
    "stinken": ("stank", "gestunken", "hat", "发臭，发恶臭"),
    "trinken": ("trank", "getrunken", "hat", "喝，饮用"),
    "ertrinken": ("ertrank", "ertrunken", "ist", "淹死，溺亡"),
    "austrinken": ("trank aus", "ausgetrunken", "hat", "喝光，饮尽"),
    "betrinken": ("betrank", "betrunken", "hat", "喝醉(sich)"),
    "winden": ("wand", "gewunden", "hat", "缠绕，编织；扭动(sich)"),
    "überwinden": ("überwand", "überwunden", "hat", "克服，战胜"),
    "zwingen": ("zwang", "gezwungen", "hat", "强迫，逼迫(zu)"),
    "erzwingen": ("erzwang", "erzwungen", "hat", "迫使，强行获取"),
    "aufzwingen": ("zwang auf", "aufgezwungen", "hat", "强加给(Dativ)"),
    "beginnen": ("begann", "begonnen", "hat", "开始，着手"),
    "gewinnen": ("gewann", "gewonnen", "hat", "赢得，获胜，获取"),
    "schwimmen": ("schwamm", "geschwommen", "ist/hat", "游泳，漂浮"),
    "rinnen": ("rann", "geronnen", "ist", "流淌，淌下"),
    "zerrinnen": ("zerrann", "zerronnen", "ist", "融化，消逝"),
    "spinnen": ("spann", "gesponnen", "hat", "纺纱；胡思乱想"),
    "sinnen": ("sann", "gesonnen", "hat", "沉思，图谋"),
    "besinnen": ("besann", "besonnen", "hat", "回忆，反省(sich auf)"),

    # ── Ablautreihe 4: e -> a -> o ─────────────────────────────────────────────
    "befehlen": ("befahl", "befohlen", "hat", "命令，指示"),
    "empfehlen": ("empfahl", "empfohlen", "hat", "推荐，建议"),
    "stehlen": ("stahl", "gestohlen", "hat", "偷窃，偷"),
    "gebären": ("gebar", "geboren", "hat/ist", "生育，诞生"),
    "brechen": ("brach", "gebrochen", "hat/ist", "折断，打破，违犯"),
    "abbrechen": ("brach ab", "abgebrochen", "hat/ist", "中断，拆除"),
    "aufbrechen": ("brach auf", "aufgebrochen", "ist/hat", "启程，出发；撬开"),
    "einbrechen": ("brach ein", "eingebrochen", "ist", "破门盗窃；坍塌"),
    "unterbrechen": ("unterbrach", "unterbrochen", "hat", "打断，中断"),
    "verbrechen": ("verbrach", "verbrochen", "hat", "犯罪，做错事"),
    "ausbrechen": ("brach aus", "ausgebrochen", "ist", "爆发，逃脱"),
    "zusammenbrechen": ("brach zusammen", "zusammengebrochen", "ist", "崩溃，瓦解"),
    "helfen": ("half", "geholfen", "hat", "帮助，协助(Dativ)"),
    "aushelfen": ("half aus", "ausgeholfen", "hat", "临时帮忙，救急"),
    "mithelfen": ("half mit", "mitgeholfen", "hat", "共同帮忙"),
    "weiterhelfen": ("half weiter", "weitergeholfen", "hat", "给予进一步帮助"),
    "nehmen": ("nahm", "genommen", "hat", "拿，选用，服用"),
    "abnehmen": ("nahm ab", "abgenommen", "hat", "减少，减轻(体重)；摘下"),
    "annehmen": ("nahm an", "angenommen", "hat", "接受，采纳；假设"),
    "aufnehmen": ("nahm auf", "aufgenommen", "hat", "录音，摄录；接纳；吸收"),
    "ausnehmen": ("nahm aus", "ausgenommen", "hat", "掏空；除外"),
    "einnehmen": ("nahm ein", "eingenommen", "hat", "服用(药)；占领；收入"),
    "festnehmen": ("nahm fest", "festgenommen", "hat", "逮捕，拘捕"),
    "mitnehmen": ("nahm mit", "mitgenommen", "hat", "随身带走，捎带"),
    "teilnehmen": ("nahm teil", "teilgenommen", "hat", "参加，参与(an)"),
    "übernehmen": ("übernahm", "übernommen", "hat", "接管，承担"),
    "unternehmen": ("unternahm", "unternommen", "hat", "着手，进行，从事"),
    "vernehmen": ("vernahm", "vernommen", "hat", "听见；审讯"),
    "vornehmen": ("nahm vor", "vorgenommen", "hat", "打算，着手进行(sich)"),
    "wahrnehmen": ("nahm wahr", "wahrgenommen", "hat", "感知，觉察；把握(机会)"),
    "zunehmen": ("nahm zu", "zugenommen", "hat", "增加，增重"),
    "herausnehmen": ("nahm heraus", "herausgenommen", "hat", "取出，挑出"),
    "zurücknehmen": ("nahm zurück", "zurückgenommen", "hat", "收回，撤回"),
    "sprechen": ("sprach", "gesprochen", "hat", "说话，谈话"),
    "absprechen": ("sprach ab", "abgesprochen", "hat", "商定，协商；剥夺"),
    "ansprechen": ("sprach an", "angesprochen", "hat", "搭话，向...提议；产生共鸣"),
    "aussprechen": ("sprach aus", "ausgesprochen", "hat", "发音；表达，说出"),
    "besprechen": ("besprach", "besprochen", "hat", "讨论，商讨，评述"),
    "entsprechen": ("entsprach", "entsprochen", "hat", "符合，相当于(Dativ)"),
    "versprechen": ("versprach", "versprochen", "hat", "答应，承诺；口误(sich)"),
    "widersprechen": ("widersprach", "widersprochen", "hat", "反驳，与...相矛盾(Dativ)"),
    "zusprechen": ("sprach zu", "zugesprochen", "hat", "判给，赋予；鼓励"),
    "vorsprechen": ("sprach vor", "vorgesprochen", "hat", "试镜，口头申请"),
    "stechen": ("stach", "gestochen", "hat", "刺，扎，叮咬"),
    "anstechen": ("stach an", "angestochen", "hat", "刺破，开桶"),
    "bestehen": ("bestand", "bestanden", "hat", "通过(考试)；存在；坚持(auf)"),
    "entstehen": ("entstand", "entstanden", "ist", "产生，形成，出现"),
    "gestehen": ("gestand", "gestanden", "hat", "承认，供认"),
    "überstehen": ("überstand", "überstanden", "hat", "克服，度过(危机)"),
    "widerstehen": ("widerstand", "widerstanden", "hat", "抵抗，抗拒(Dativ)"),
    "sterben": ("starb", "gestorben", "ist", "死，去世，阵亡(an)"),
    "aussterben": ("starb aus", "ausgestorben", "ist", "灭绝，绝种"),
    "verderben": ("verdarb", "verdorben", "hat/ist", "变质，败坏，搞砸"),
    "treffen": ("traf", "getroffen", "hat", "遇见，击中；碰头(sich mit)"),
    "antreffen": ("traf an", "angetroffen", "hat", "遇见，碰见"),
    "betreffen": ("betraf", "betroffen", "hat", "涉及，关乎"),
    "eintreffen": ("traf ein", "eingetroffen", "ist", "到达；应验，实现"),
    "übertreffen": ("übertraf", "übertroffen", "hat", "超过，胜过"),
    "zutreffen": ("traf zu", "zugetroffen", "hat", "符合事实，适用(auf)"),
    "werfen": ("warf", "geworfen", "hat", "扔，投掷"),
    "abwerfen": ("warf ab", "abgeworfen", "hat", "扔下，抛弃；带来利润"),
    "auswerfen": ("warf aus", "ausgeworfen", "hat", "抛出，吐出"),
    "einwerfen": ("warf ein", "eingeworfen", "hat", "投入(信箱)；插话"),
    "entwerfen": ("entwarf", "entworfen", "hat", "设计，起草，构思"),
    "vorwerfen": ("warf vor", "vorgeworfen", "hat", "指责，责备(Dativ)"),
    "wegwerfen": ("warf weg", "weggeworfen", "hat", "扔掉，丢弃"),
    "aufwerfen": ("warf auf", "aufgeworfen", "hat", "提出(问题)"),
    "hinwerfen": ("warf hin", "hingeworfen", "hat", "扔下，放弃"),
    "werben": ("warb", "geworben", "hat", "做广告，争取，招募(für/um)"),
    "bewerben": ("bewarb", "beworben", "hat", "申请，应聘(sich um/für)"),
    "erwerben": ("erwarb", "erworben", "hat", "获得，购得，学会"),
    "anwerben": ("warb an", "angeworben", "hat", "招募，雇佣"),
    "gelten": ("galt", "gegolten", "hat", "有效，适用，被视为(als)"),
    "bergen": ("barg", "geborgen", "hat", "打捞，抢救，蕴含"),
    "verbergen": ("verbarg", "verborgen", "hat", "隐藏，隐瞒"),

    # ── Ablautreihe 5: e -> a -> e ─────────────────────────────────────────────
    "essen": ("aß", "gegessen", "hat", "吃"),
    "aufessen": ("aß auf", "aufgegessen", "hat", "吃光，吃完"),
    "fressen": ("fraß", "gefressen", "hat", "(动物)吃，大吃大喝"),
    "geben": ("gab", "gegeben", "hat", "给，给予；存在(es gibt)"),
    "abgeben": ("gab ab", "abgegeben", "hat", "交出，提交；排放"),
    "angeben": ("gab an", "angegeben", "hat", "说明，指明；吹牛"),
    "aufgeben": ("gab auf", "aufgegeben", "hat", "放弃；邮寄；布置(作业)"),
    "ausgeben": ("gab aus", "ausgegeben", "hat", "花费，支出；发行"),
    "eingeben": ("gab ein", "eingegeben", "hat", "输入(数据)；服药"),
    "ergeben": ("ergab", "ergeben", "hat", "得出，表明；产生；屈服(sich)"),
    "herausgeben": ("gab heraus", "herausgegeben", "hat", "出版，发行；找零"),
    "nachgeben": ("gab nach", "nachgegeben", "hat", "让步，屈服"),
    "übergeben": ("übergab", "übergeben", "hat", "移交，递交；呕吐(sich)"),
    "vergeben": ("vergab", "vergeben", "hat", "原谅；授予，分配"),
    "weitergeben": ("gab weiter", "weitergegeben", "hat", "转交，传递"),
    "zugeben": ("gab zu", "zugegeben", "hat", "承认；添加"),
    "zurückgeben": ("gab zurück", "zurückgegeben", "hat", "归还，退回"),
    "bekanntgeben": ("gab bekannt", "bekanntgegeben", "hat", "公布，宣布"),
    "genesen": ("genas", "genesen", "ist", "康复，痊愈"),
    "geschehen": ("geschah", "geschehen", "ist", "发生"),
    "lesen": ("las", "gelesen", "hat", "读，阅读"),
    "ablesen": ("las ab", "abgelesen", "hat", "照着念；读取(数值)"),
    "auslesen": ("las aus", "ausgelesen", "hat", "读完；挑选，筛选"),
    "durchlesen": ("las durch", "durchgelesen", "hat", "通读，浏览"),
    "vorlesen": ("las vor", "vorgelesen", "hat", "朗读给...听"),
    "nachlesen": ("las nach", "nachgelesen", "hat", "查阅，补读"),
    "messen": ("maß", "gemessen", "hat", "测量，衡量"),
    "abmessen": ("maß ab", "abgemessen", "hat", "丈量，测定"),
    "bemessen": ("bemaß", "bemessen", "hat", "评估，确定"),
    "sehen": ("sah", "gesehen", "hat", "看见，看"),
    "ansehen": ("sah an", "angesehen", "hat", "注视，看；看待(als)"),
    "aufsehen": ("sah auf", "aufgesehen", "hat", "抬头看；引起轰动"),
    "aussehen": ("sah aus", "ausgesehen", "hat", "看起来，显得"),
    "einsehen": ("sah ein", "eingesehen", "hat", "查阅；认识到，领悟"),
    "fernsehen": ("sah fern", "ferngesehen", "hat", "看电视"),
    "nachsehen": ("sah nach", "nachgesehen", "hat", "查看，查对；目送"),
    "übersehen": ("übersah", "übersehen", "hat", "忽略，漏看；俯瞰"),
    "vorsehen": ("sah vor", "vorgesehen", "hat", "预先安排，规定；小心(sich)"),
    "zusehen": ("sah zu", "zugesehen", "hat", "旁观，注视(Dativ)"),
    "wiedersehen": ("sah wieder", "wiedergesehen", "hat", "重逢，再见"),
    "treten": ("trat", "getreten", "ist/hat", "踩，踏，走"),
    "antreten": ("trat an", "angetreten", "ist/hat", "走马上任，参赛，列队"),
    "auftreten": ("trat auf", "aufgetreten", "ist", "登台；发生，出现"),
    "beitreten": ("trat bei", "beigetreten", "ist", "加入(组织、协会)(Dativ)"),
    "eintreten": ("trat ein", "eingetreten", "ist", "进入；发生；加入"),
    "zurücktreten": ("trat zurück", "zurückgetreten", "ist", "后退；辞职，退位"),
    "vertreten": ("vertrat", "vertreten", "hat", "代表，代理，主张"),
    "abtreten": ("trat ab", "abgetreten", "hat/ist", "退场；让与(权利)"),
    "übertreten": ("übertrat", "übertreten", "hat/ist", "越界，改信"),
    "vergessen": ("vergaß", "vergessen", "hat", "忘记，遗忘"),
    "sitzen": ("saß", "gesessen", "hat/ist", "坐，就座"),
    "besitzen": ("besaß", "besessen", "hat", "拥有，占有"),
    "liegen": ("lag", "gelegen", "hat/ist", "躺，平放，位于"),
    "anliegen": ("lag an", "angelegen", "hat", "紧贴；靠着；关乎"),
    "unterliegen": ("unterlag", "unterlegen", "ist", "屈服于；遭受；受制于(Dativ)"),
    "vorliegen": ("lag vor", "vorgelegen", "hat", "摆在面前，存在，有"),

    # ── Ablautreihe 6: a -> u -> a ─────────────────────────────────────────────
    "backen": ("buk", "gebacken", "hat", "烘焙，烤"),
    "fahren": ("fuhr", "gefahren", "ist/hat", "驾驶，乘车，行驶"),
    "abfahren": ("fuhr ab", "abgefahren", "ist", "出发，开出"),
    "anfahren": ("fuhr an", "angefahren", "ist/hat", "驶来，启动；撞上"),
    "erfahren": ("erfuhr", "erfahren", "hat", "获悉，得知；经历"),
    "mitfahren": ("fuhr mit", "mitgefahren", "ist", "搭车，一同乘车"),
    "überfahren": ("überfuhr", "überfahren", "hat", "压过，辗过"),
    "verfahren": ("verfuhr", "verfahren", "ist/hat", "采取行动，处理；迷路(sich)"),
    "weiterfahren": ("fuhr weiter", "weitergefahren", "ist", "继续行驶"),
    "zurückfahren": ("fuhr zurück", "zurückgefahren", "ist", "返回，倒车；减少"),
    "losfahren": ("fuhr los", "losgefahren", "ist", "出发，动身"),
    "graben": ("grub", "gegraben", "hat", "挖掘，掘地"),
    "begraben": ("begrub", "begraben", "hat", "埋葬，葬送"),
    "laden": ("lud", "geladen", "hat", "装载；充电；邀请"),
    "aufladen": ("lud auf", "aufgeladen", "hat", "装上；充电"),
    "ausladen": ("lud aus", "ausgeladen", "hat", "卸货；取消邀请"),
    "einladen": ("lud ein", "eingeladen", "hat", "邀请"),
    "herunterladen": ("lud herunter", "heruntergeladen", "hat", "下载"),
    "hochladen": ("lud hoch", "hochgeladen", "hat", "上传"),
    "schaffen": ("schuf", "geschaffen", "hat", "创造，塑造"),
    "erschaffen": ("erschuf", "erschaffen", "hat", "创造，开创"),
    "schlagen": ("schlug", "geschlagen", "hat", "打，击打，敲"),
    "abschlagen": ("schlug ab", "abgeschlagen", "hat", "打掉；拒绝"),
    "einschlagen": ("schlug ein", "eingeschlagen", "hat/ist", "打碎；打入；采纳(道路)"),
    "nachschlagen": ("schlug nach", "nachgeschlagen", "hat", "查阅，翻查"),
    "vorschlagen": ("schlug vor", "vorgeschlagen", "hat", "提议，建议"),
    "fehlschlagen": ("schlug fehl", "fehlgeschlagen", "ist", "失败，落空"),
    "tragen": ("trug", "getragen", "hat", "穿，戴，背，携带；承受"),
    "beitragen": ("trug bei", "beigetragen", "hat", "做出贡献，有助于(zu)"),
    "betragen": ("betrug", "betragen", "hat", "总计，达到；表现(sich)"),
    "eintragen": ("trug ein", "eingetragen", "hat", "填入，登记，载入"),
    "ertragen": ("ertrug", "ertragen", "hat", "忍受，承受"),
    "übertragen": ("übertrug", "übertragen", "hat", "转播；转让；转录"),
    "vertragen": ("vertrug", "vertragen", "hat", "忍受；和睦相处(sich mit)"),
    "vortragen": ("trug vor", "vorgetragen", "hat", "作报告，朗诵，陈述"),
    "austragen": ("trug aus", "ausgetragen", "hat", "分送；举办(比赛)"),
    "wachsen": ("wuchs", "gewachsen", "ist", "生长，成长，增加"),
    "aufwachsen": ("wuchs auf", "aufgewachsen", "ist", "长大，成长"),
    "erwachsen": ("erwuchs", "erwachsen", "ist", "产生，形成"),
    "hinauswachsen": ("wuchs hinaus", "hinausgewachsen", "ist", "超出，超越(über)"),
    "waschen": ("wusch", "gewaschen", "hat", "洗，洗涤"),
    "abwaschen": ("wusch ab", "abgewaschen", "hat", "洗掉，洗餐具"),

    # ── Ablautreihe 7: a/au/o/u/ei -> ie/i -> a/au/o/u/ei ─────────────────────
    "blasen": ("blies", "geblasen", "hat", "吹，吹奏，刮风"),
    "aufblasen": ("blies auf", "aufgeblasen", "hat", "充气，吹大"),
    "braten": ("briet", "gebraten", "hat", "煎，炸，烤"),
    "anbraten": ("briet an", "angebraten", "hat", "微煎，煎一下"),
    "fallen": ("fiel", "gefallen", "ist", "落下，跌倒，下降"),
    "abfallen": ("fiel ab", "abgefallen", "ist", "掉落；下降；背叛"),
    "anfallen": ("fiel an", "angefallen", "hat/ist", "袭击；产生(费用)"),
    "auffallen": ("fiel auf", "aufgefallen", "ist", "引人注目，显眼(Dativ)"),
    "ausfallen": ("fiel aus", "ausgefallen", "ist", "取消，停开；脱落"),
    "durchfallen": ("fiel durch", "durchgefallen", "ist", "不及格，考试未通过"),
    "einfallen": ("fiel ein", "eingefallen", "ist", "想起；倒塌；入侵"),
    "gefallen": ("gefiel", "gefallen", "hat", "使喜欢，合心意(Dativ)"),
    "überfallen": ("überfiel", "überfallen", "hat", "袭击，打劫"),
    "fangen": ("fing", "gefangen", "hat", "捕捉，抓住"),
    "anfangen": ("fing an", "angefangen", "hat", "开始，着手"),
    "auffangen": ("fing auf", "aufgefangen", "hat", "接住；拦截；化解"),
    "empfangen": ("empfing", "empfangen", "hat", "接待；接收，收到"),
    "abfangen": ("fing ab", "abgefangen", "hat", "截获，阻截"),
    "halten": ("hielt", "gehalten", "hat", "拿着，保持；停下；认为(für)"),
    "abhalten": ("hielt ab", "abgehalten", "hat", "举办；阻止(von)"),
    "anhalten": ("hielt an", "angehalten", "hat/ist", "停住；持续"),
    "aufhalten": ("hielt auf", "aufgehalten", "hat", "阻挡；逗留(sich)"),
    "behalten": ("behielt", "behalten", "hat", "保留，记住"),
    "einhalten": ("hielt ein", "eingehalten", "hat", "遵守，遵照(Frist)"),
    "enthalten": ("enthielt", "enthalten", "hat", "包含，含有；弃权(sich)"),
    "erhalten": ("erhielt", "erhalten", "hat", "收到，得到；保持"),
    "festhalten": ("hielt fest", "festgehalten", "hat", "抓紧；坚持；记录"),
    "unterhalten": ("unterhielt", "unterhalten", "hat", "交谈；娱乐；维持"),
    "verhalten": ("verhielt", "verhalten", "hat", "表现，处于...情况(sich)"),
    "zurückhalten": ("hielt zurück", "zurückgehalten", "hat", "抑制，克制"),
    "durchhalten": ("hielt durch", "durchgehalten", "hat", "坚持到底"),
    "hängen": ("hing", "gehangen", "hat/ist", "悬挂，挂着"),
    "abhängen": ("hing ab", "abgehangen", "hat", "取决于(von)"),
    "zusammenhängen": ("hing zusammen", "zusammengehangen", "hat", "与...相联系"),
    "heißen": ("hieß", "geheißen", "hat", "名叫；意味着"),
    "lassen": ("ließ", "gelassen", "hat", "让，使；留下；允许"),
    "anlassen": ("ließ an", "angelassen", "hat", "开着(机器)；不脱(衣服)"),
    "auslassen": ("ließ aus", "ausgelassen", "hat", "遗漏，省略；发泄"),
    "entlassen": ("entließ", "entlassen", "hat", "解雇，准许出院"),
    "hinterlassen": ("hinterließ", "hinterlassen", "hat", "留下，遗留"),
    "nachlassen": ("ließ nach", "nachgelassen", "hat", "减弱，减退"),
    "überlassen": ("überließ", "überlassen", "hat", "托付，转让，让给"),
    "verlassen": ("verließ", "verlassen", "hat", "离开，抛弃；信赖(sich auf)"),
    "zulassen": ("ließ zu", "zugelassen", "hat", "允许，准许，许可"),
    "zurücklassen": ("ließ zurück", "zurückgelassen", "hat", "留下，遗落"),
    "laufen": ("lief", "gelaufen", "ist", "跑，走；运转，进行"),
    "ablaufen": ("lief ab", "abgelaufen", "ist", "流走；到期；进行"),
    "anlaufen": ("lief an", "angelaufen", "ist", "起跑；靠岸；启动"),
    "auslaufen": ("lief aus", "ausgelaufen", "ist", "漏出；到期终止"),
    "einlaufen": ("lief ein", "eingelaufen", "ist", "进港；缩水"),
    "verlaufen": ("verlief", "verlaufen", "ist/hat", "延伸，进行；迷路(sich)"),
    "vorbeilaufen": ("lief vorbei", "vorbeigelaufen", "ist", "从旁边跑过"),
    "raten": ("riet", "geraten", "hat", "建议(Dativ)；猜测"),
    "abraten": ("riet ab", "abgeraten", "hat", "劝阻(von)"),
    "beraten": ("beriet", "beraten", "hat", "提供咨询，商讨"),
    "geraten": ("geriet", "geraten", "ist", "陷入，处于(in)"),
    "verraten": ("verriet", "verraten", "hat", "背叛，泄密"),
    "rufen": ("rief", "gerufen", "hat", "呼喊，召唤"),
    "abrufen": ("rief ab", "abgerufen", "hat", "检索，调取；召回"),
    "anrufen": ("rief an", "angerufen", "hat", "打电话"),
    "aufrufen": ("rief auf", "aufgerufen", "hat", "号召，呼吁；调用"),
    "ausrufen": ("rief aus", "ausgerufen", "hat", "宣布，宣告；惊呼"),
    "hervorrufen": ("rief hervor", "hervorgerufen", "hat", "引起，引发"),
    "widerrufen": ("widerrief", "widerrufen", "hat", "撤销，废除"),
    "schlafen": ("schlief", "geschlafen", "hat", "睡觉"),
    "einschlafen": ("schlief ein", "eingeschlafen", "ist", "入睡，睡着"),
    "ausschlafen": ("schlief aus", "ausgeschlafen", "hat", "睡足，睡个够"),
    "verschlafen": ("verschlief", "verschlafen", "hat", "睡过头；错过"),
    "durchschlafen": ("schlief durch", "durchgeschlafen", "hat", "一觉睡到天亮"),
    "stoßen": ("stieß", "gestoßen", "hat/ist", "撞击，推；偶遇(auf)"),
    "abstoßen": ("stieß ab", "abgestoßen", "hat", "推开；抛售；令人反感"),
    "anstoßen": ("stieß an", "angestoßen", "hat", "碰杯；触碰；推动"),
    "ausstoßen": ("stieß aus", "ausgestoßen", "hat", "排放，吐出；驱逐"),
    "zusammenstoßen": ("stieß zusammen", "zusammengestoßen", "ist", "相撞，冲突"),

    # ── Others & High Frequency ───────────────────────────────────────────────
    "gehen": ("ging", "gegangen", "ist", "走，去；进行"),
    "abgehen": ("ging ab", "abgegangen", "ist", "离去，离开；脱落"),
    "angehen": ("ging an", "angegangen", "ist/hat", "走近；涉及，关乎；亮起"),
    "aufgehen": ("ging auf", "aufgegangen", "ist", "升起；开放；显明"),
    "ausgehen": ("ging aus", "ausgegangen", "ist", "外出；熄灭；源于(von)"),
    "begehen": ("beging", "begangen", "hat", "做出(错事、罪行)；庆祝"),
    "durchgehen": ("ging durch", "durchgegangen", "ist", "穿过；通读；获通过"),
    "eingehen": ("ging ein", "eingegangen", "ist", "到达；同意(auf)；枯萎"),
    "entgehen": ("entging", "entgangen", "ist", "逃脱；错过"),
    "nachgehen": ("ging nach", "nachgegangen", "ist", "跟在...后面；调查，探究"),
    "umgehen": ("ging um", "umgegangen", "ist", "对待(mit)；绕行"),
    "untergehen": ("ging unter", "untergegangen", "ist", "下沉，沉没，灭亡"),
    "vergehen": ("verging", "vergangen", "ist", "流逝，消逝"),
    "vorgehen": ("ging vor", "vorgegangen", "ist", "走在前面；采取行动；发生"),
    "weitergehen": ("ging weiter", "weitergegangen", "ist", "继续前行，继续"),
    "zergehen": ("zerging", "zergangen", "ist", "融化，溶化"),
    "zugehen": ("ging zu", "zugegangen", "ist", "关上；走向；发生"),
    "zurückgehen": ("ging zurück", "zurückgegangen", "ist", "返回；下降"),
    "hinausgehen": ("ging hinaus", "hinausgegangen", "ist", "走出去，超出(über)"),
    "kommen": ("kam", "gekommen", "ist", "来，来到"),
    "abkommen": ("kam ab", "abgekommen", "ist", "偏离，脱离(von)"),
    "ankommen": ("kam an", "angekommen", "ist", "到达；取决于(auf)"),
    "auskommen": ("kam aus", "ausgekommen", "ist", "和睦相处(mit)；应付，够用"),
    "bekommen": ("bekam", "bekommen", "hat", "得到，收到"),
    "durchkommen": ("kam durch", "durchgekommen", "ist", "通过，度过难关"),
    "entkommen": ("entkam", "entkommen", "ist", "逃脱，逃走"),
    "herkommen": ("kam her", "hergekommen", "ist", "来到这里，来自"),
    "mitkommen": ("kam mit", "mitgekommen", "ist", "同来，跟上"),
    "nachkommen": ("kam nach", "nachgekommen", "ist", "随后赶来；履行(Pflicht)"),
    "umkommen": ("kam um", "umgekommen", "ist", "丧生，遇难"),
    "unterkommen": ("kam unter", "untergekommen", "ist", "找到住宿，安置"),
    "vorkommen": ("kam vor", "vorgekommen", "ist", "发生；显得，觉得(Dativ)"),
    "weiterkommen": ("kam weiter", "weitergekommen", "ist", "取得进展，前进"),
    "zurückkommen": ("kam zurück", "zurückgekommen", "ist", "回来，返回"),
    "zusammenkommen": ("kam zusammen", "zusammengekommen", "ist", "聚集，聚会"),
    "stehen": ("stand", "gestanden", "hat/ist", "站立，处于"),
    "abstehen": ("stand ab", "abgestanden", "hat", "凸出，翘起"),
    "aufstehen": ("stand auf", "aufgestanden", "ist", "起床，起立"),
    "beistehen": ("stand bei", "beigestanden", "hat", "支持，援助(Dativ)"),
    "hinterstehen": ("stand hinter", "hintergestanden", "hat", "支持，位于...之后"),
    "verstehen": ("verstand", "verstanden", "hat", "理解，懂；精通(von)"),
    "vorstehen": ("stand vor", "vorgestanden", "hat", "突出；主管(Dativ)"),
    "zustehen": ("stand zu", "zugestanden", "hat", "属于，有权享有(Dativ)"),
    "tun": ("tat", "getan", "hat", "做，干，行动"),
    "abtun": ("tat ab", "abgetan", "hat", "打发，不予理会"),
    "antun": ("tat an", "angetan", "hat", "加害于，使遭受；穿上"),
    "auftun": ("tat auf", "aufgetan", "hat", "敞开；展现出(sich)"),
    "guttun": ("tat gut", "gutgetan", "hat", "有益于，对...有好处(Dativ)"),
    "leidtun": ("tat leid", "leidgetan", "hat", "感到抱歉，遗憾(Dativ)"),
    "mittun": ("tat mit", "mitgetan", "hat", "参与，一起做"),
    "wehtun": ("tat weh", "wehgetan", "hat", "疼痛，伤害(Dativ)"),
    "mittragen": ("trug mit", "mitgetragen", "hat", "共同承担"),
}

# Backwards compatibility alias
IRREGULAR_VERBS_DB = IRREGULAR_VERBS


# ==============================================================================
# Verb Trio Data Class & O(1) Bidirectional Index
# ==============================================================================

class VerbTrio(tuple):
    """
    Structured 4-tuple (Präteritum, Partizip II, Hilfsverb, Definition_zh)
    with named attribute access, dict indexing ('praeteritum', 'infinitiv'), and dictionary serialization.
    """
    def __new__(cls, praeteritum: str, partizip2: str, hilfsverb: str, definition_zh: str, infinitiv: str = ""):
        obj = super(VerbTrio, cls).__new__(cls, (praeteritum, partizip2, hilfsverb, definition_zh))
        obj.infinitiv = infinitiv
        obj.praeteritum = praeteritum
        obj.partizip2 = partizip2
        obj.hilfsverb = hilfsverb
        obj.definition_zh = definition_zh
        return obj

    def __getitem__(self, item):
        if isinstance(item, str):
            if item == "infinitiv":
                return self.infinitiv
            if item in ("praeteritum", "präteritum"):
                return self.praeteritum
            if item in ("partizip2", "partizip_2", "partizip_ii", "partizip"):
                return self.partizip2
            if item in ("hilfsverb", "auxiliary"):
                return self.hilfsverb
            if item in ("definition_zh", "definition", "def_zh", "meaning"):
                return self.definition_zh
            raise KeyError(item)
        return super().__getitem__(item)

    def get(self, key: str, default=None):
        try:
            return self[key]
        except (KeyError, IndexError, TypeError):
            return default

    def to_dict(self) -> Dict[str, str]:
        return {
            "infinitiv": self.infinitiv,
            "praeteritum": self.praeteritum,
            "partizip2": self.partizip2,
            "hilfsverb": self.hilfsverb,
            "definition_zh": self.definition_zh,
        }

    def __repr__(self) -> str:
        return f"<VerbTrio {self.infinitiv}: {self.praeteritum} - {self.hilfsverb} {self.partizip2} ({self.definition_zh})>"


# Build bidirectional reverse lookup index mapping any surface form -> base infinitiv
_REVERSE_VERB_INDEX: Dict[str, str] = {}

# Common 3rd person singular present vowel-change stems
_PRESENT_VOWEL_CHANGES: Dict[str, str] = {
    "sieht": "sehen", "siehst": "sehen",
    "liest": "lesen",
    "gibt": "geben", "gibst": "geben",
    "nimmt": "nehmen", "nimmst": "nehmen",
    "spricht": "sprechen", "sprichst": "sprechen",
    "bricht": "brechen", "brichst": "brechen",
    "trifft": "treffen", "triffst": "treffen",
    "hilft": "helfen", "hilfst": "helfen",
    "stirbt": "sterben", "stirbst": "sterben",
    "wirft": "werfen", "wirfst": "werfen",
    "gilt": "gelten", "giltst": "gelten",
    "stiehlt": "stehlen", "stiehlst": "stehlen",
    "empfiehlt": "empfehlen", "empfiehlst": "empfehlen",
    "befiehlt": "befehlen", "befiehlst": "befehlen",
    "geschieht": "geschehen",
    "isst": "essen",
    "frisst": "fressen",
    "misst": "messen",
    "fährt": "fahren", "fährst": "fahren",
    "schläft": "schlafen", "schläfst": "schlafen",
    "fällt": "fallen", "fällst": "fallen",
    "läuft": "laufen", "läufst": "laufen",
    "wächst": "wachsen",
    "wäscht": "waschen", "wäschst": "waschen",
    "trägt": "tragen", "trägst": "tragen",
    "schlägt": "schlagen", "schlägst": "schlagen",
    "lässt": "lassen",
    "brät": "braten", "brätst": "braten",
    "rät": "raten", "rätst": "raten",
    "bläst": "blasen",
    "stößt": "stoßen",
    "lädt": "laden", "lädst": "laden",
    "schafft": "schaffen",
    "hält": "halten", "hältst": "halten",
    "fängt": "fangen", "fängst": "fangen",
    "hängt": "hängen",
    "weiß": "wissen", "weißt": "wissen",
}

for _inf, (_praet, _p2, _hilf, _def) in IRREGULAR_VERBS.items():
    _inf_low = _inf.lower()
    _REVERSE_VERB_INDEX[_inf_low] = _inf

    # Index full Präteritum (e.g. 'ging', 'stand auf')
    _praet_low = _praet.lower()
    _REVERSE_VERB_INDEX[_praet_low] = _inf
    # If separable präteritum like 'stand auf' or 'nahm mit', also index unified 'aufstand' / 'mitnahm'
    if " " in _praet_low:
        _parts = _praet_low.split()
        if len(_parts) == 2:
            _verb_pt, _pfx_pt = _parts[0], _parts[1]
            _REVERSE_VERB_INDEX[f"{_pfx_pt}{_verb_pt}"] = _inf

    # Index Partizip II (e.g. 'gegangen', 'aufgestanden')
    _p2_low = _p2.lower()
    _REVERSE_VERB_INDEX[_p2_low] = _inf

    # Index common past tense inflection endings (-st, -en, -t, -e)
    # e.g., gingst, gingen, gingt; sahen, saht, sahst; lasen, last
    _praet_stem = _praet.split()[0].lower()
    for _end in ["st", "en", "t", "e", "est", "et"]:
        _REVERSE_VERB_INDEX[f"{_praet_stem}{_end}"] = _inf

# Merge present vowel change stems
for _form, _inf in _PRESENT_VOWEL_CHANGES.items():
    if _inf in IRREGULAR_VERBS and _form not in _REVERSE_VERB_INDEX:
        _REVERSE_VERB_INDEX[_form] = _inf

# High-frequency present-tense forms for the no-lemma fallback path.
# 为什么手编而不是规则循环生成：强动词现在时变音（e→i/ie、a→ä）没有完整表，
# 规则循环会对未列出的变音词生成错误形式（如 vergisst→vergesst 而非 vergessen），
# 比查不到更糟。主路径是 lemma-first（spaCy 已正确还原）；这张表只兜无 lemma 的
# 旧客户端/纯 Python 路径，覆盖最高频的助动词/情态动词/常用强动词现在时。
_AUX_MODAL_PRESENT: Dict[str, str] = {
    # sein
    "ist": "sein", "bin": "sein", "bist": "sein", "sind": "sein", "seid": "sein",
    # haben
    "hat": "haben", "habe": "haben", "hast": "haben", "haben": "haben", "habt": "haben",
    # werden
    "wird": "werden", "werde": "werden", "wirst": "werden", "werdet": "werden",
    # modals
    "will": "wollen", "willst": "wollen", "wollt": "wollen",
    "kann": "können", "kannst": "können", "könnt": "können",
    "muss": "müssen", "musst": "müssen", "müsst": "müssen",
    "darf": "dürfen", "darfst": "dürfen", "dürft": "dürfen",
    "soll": "sollen", "sollst": "sollen", "sollt": "sollen",
    "mag": "mögen", "magst": "mögen", "mögt": "mögen",
    # tun
    "tut": "tun", "tue": "tun", "tust": "tun",
    # 高频无变音强动词（现在时词干 = 不定式词干）
    "geht": "gehen", "gehst": "gehen", "gehe": "gehen", "gehen": "gehen",
    "steht": "stehen", "stehst": "stehen",
    "trinkt": "trinken", "trinkst": "trinken", "trinke": "trinken",
    "singt": "singen", "singst": "singen", "singe": "singen",
    "findet": "finden", "findest": "finden", "finde": "finden",
    "bleibt": "bleiben", "bleibst": "bleiben", "bleibe": "bleiben",
    "schreibt": "schreiben", "schreibst": "schreiben", "schreibe": "schreiben",
    "liest": "lesen",  # 已在 _PRESENT_VOWEL_CHANGES，防御性重复无害
    "versteht": "verstehen", "verstehst": "verstehen",
    "beginnt": "beginnen", "beginne": "beginnen",
    "bringt": "bringen", "bringst": "bringen", "bringe": "bringen",
    "denkt": "denken", "denkst": "denken",
    "heißt": "heißen", "heiße": "heißen",
    "kennt": "kennen", "kennst": "kennen",
    "kommt": "kommen", "kommst": "kommen", "komme": "kommen",
    "meint": "meinen", "meinst": "meinen",
    "nennt": "nennen", "nennst": "nennen",
    "sagt": "sagen", "sagst": "sagen", "sage": "sagen",
    "setzt": "setzen", "setze": "setzen",
    "spielt": "spielen", "spielst": "spielen", "spiele": "spielen",
    "arbeitet": "arbeiten", "arbeite": "arbeiten",
    "wohnt": "wohnen", "wohnst": "wohnen", "wohne": "wohnen",
    "fragt": "fragen", "fragst": "fragen", "frage": "fragen",
    "antwortet": "antworten", "antworte": "antworten",
    "macht": "machen", "machst": "machen", "mache": "machen",
}
for _form, _inf in _AUX_MODAL_PRESENT.items():
    if _inf in IRREGULAR_VERBS and _form not in _REVERSE_VERB_INDEX:
        _REVERSE_VERB_INDEX[_form] = _inf


def lookup_irregular_verb(form_or_lemma: str) -> Optional[VerbTrio]:
    """
    O(1) Bidirectional lookup for Goethe strong/irregular verbs.
    Accepts Infinitiv (e.g. 'gehen'), Präteritum (e.g. 'ging'), Partizip II (e.g. 'gegangen'),
    or inflected forms (e.g. 'sieht', 'verstand').
    Returns a VerbTrio tuple: (praeteritum, partizip2, hilfsverb, definition_zh)
    with .infinitiv, .praeteritum, .partizip2, .hilfsverb, .definition_zh and .to_dict().
    """
    if not form_or_lemma:
        return None
    
    clean = form_or_lemma.strip().lower()
    
    # 1. Direct O(1) lookup in reverse index
    if clean in _REVERSE_VERB_INDEX:
        inf = _REVERSE_VERB_INDEX[clean]
        praet, p2, hilf, def_zh = IRREGULAR_VERBS[inf]
        return VerbTrio(praet, p2, hilf, def_zh, infinitiv=inf)

    # 2. Direct match in IRREGULAR_VERBS
    if clean in IRREGULAR_VERBS:
        praet, p2, hilf, def_zh = IRREGULAR_VERBS[clean]
        return VerbTrio(praet, p2, hilf, def_zh, infinitiv=clean)

    # 3. Strip reflexive pronoun prefix (e.g. 'sich erinnern' -> 'erinnern')
    if clean.startswith("sich "):
        base = clean[5:].strip()
        if base in _REVERSE_VERB_INDEX:
            inf = _REVERSE_VERB_INDEX[base]
            praet, p2, hilf, def_zh = IRREGULAR_VERBS[inf]
            return VerbTrio(praet, p2, hilf, def_zh, infinitiv=inf)

    # 4. Handle prefixed compounds for derived verbs (e.g. 'vorangehen', 'hinausfahren')
    prefixes = [
        "ab", "an", "auf", "aus", "bei", "dar", "durch", "ein", "ent", "er",
        "fort", "ge", "her", "heraus", "herein", "hin", "hinaus", "hinein",
        "hinter", "mit", "nach", "nieder", "über", "um", "unter", "ver",
        "voll", "vor", "voran", "vorbei", "weg", "weiter", "wieder", "zer",
        "zu", "zurück", "zusammen"
    ]
    for pfx in prefixes:
        if clean.startswith(pfx) and len(clean) > len(pfx) + 2:
            sub = clean[len(pfx):]
            if sub in _REVERSE_VERB_INDEX:
                base_inf = _REVERSE_VERB_INDEX[sub]
                if base_inf in IRREGULAR_VERBS:
                    praet, p2, hilf, def_zh = IRREGULAR_VERBS[base_inf]
                    derived_inf = f"{pfx}{base_inf}"
                    return VerbTrio(praet, p2, hilf, def_zh, infinitiv=derived_inf)

    return None


def is_irregular_verb(word: str) -> bool:
    """Check if word or lemma is an irregular/strong verb."""
    return lookup_irregular_verb(word) is not None


def get_verb_stammformen(verb: str) -> Optional[Dict[str, str]]:
    """Return dictionary of Stammformen for API / frontend usage."""
    entry = lookup_irregular_verb(verb)
    return entry.to_dict() if entry else None


# ==============================================================================
# 2. Supplementary Morphology Lexicon for Compound Noun Decomposition
# ==============================================================================
# Supplements core_dict.py with high-frequency root elements (nouns, verbs, adjectives)
# Format: lemma -> (cefr, pos, gender, definition_zh)
LINGUISTICS_VOCAB_EXT: Dict[str, Tuple[str, str, Optional[str], str]] = {
    # ── Foundational Root Nouns ───────────────────────────────────────────────
    "klima": ("A2", "NOUN", "Neut", "气候，气氛"),
    "schutz": ("B1", "NOUN", "Masc", "保护，防护，防范"),
    "wandel": ("B1", "NOUN", "Masc", "变化，变迁，转变"),
    "wachstum": ("B2", "NOUN", "Neut", "增长，成长，发育"),
    "modell": ("A2", "NOUN", "Neut", "模型，模式，型号"),
    "gesetz": ("B1", "NOUN", "Neut", "法律，法则，定律"),
    "ordnung": ("A2", "NOUN", "Fem", "秩序，条理，规章"),
    "staat": ("B1", "NOUN", "Masc", "国家，州"),
    "bund": ("B1", "NOUN", "Masc", "联邦，同盟，联盟"),
    "regierung": ("B1", "NOUN", "Fem", "政府，内阁"),
    "amt": ("B1", "NOUN", "Neut", "政府机构，局，公职"),
    "rat": ("B1", "NOUN", "Masc", "建议；理事会，委员会"),
    "politik": ("A2", "NOUN", "Fem", "政治，政策"),
    "recht": ("B1", "NOUN", "Neut", "权利，法律，公理"),
    "pflicht": ("B1", "NOUN", "Fem", "义务，职责"),
    "leben": ("A1", "NOUN", "Neut", "生命，生活"),
    "welt": ("A1", "NOUN", "Fem", "世界，界"),
    "raum": ("A2", "NOUN", "Masc", "空间，房间，领域"),
    "luft": ("A2", "NOUN", "Fem", "空气，空中"),
    "bau": ("B1", "NOUN", "Masc", "建筑，施工，营造"),
    "stelle": ("A2", "NOUN", "Fem", "职位，地点，位置"),
    "plan": ("A2", "NOUN", "Masc", "计划，规划，图纸"),
    "werk": ("B1", "NOUN", "Neut", "工厂，著作，作品，机械装置"),
    "form": ("A2", "NOUN", "Fem", "形式，形状，形态"),
    "bild": ("A1", "NOUN", "Neut", "图画，图像，画面"),
    "ton": ("A2", "NOUN", "Masc", "声音，音调；泥土"),
    "spiel": ("A1", "NOUN", "Neut", "游戏，比赛，戏剧"),
    "fest": ("A1", "NOUN", "Neut", "节日，庆典"),
    "zone": ("B1", "NOUN", "Fem", "区域，地带"),
    "gut": ("B1", "NOUN", "Neut", "物品，财产，庄园"),
    "wert": ("B1", "NOUN", "Masc", "价值，数值"),
    "post": ("A1", "NOUN", "Fem", "邮政，邮件，邮局"),
    "gast": ("A1", "NOUN", "Masc", "客人，宾客"),
    "boot": ("A2", "NOUN", "Neut", "小船，艇"),
    "schiff": ("A2", "NOUN", "Neut", "轮船，船只"),
    "rad": ("A1", "NOUN", "Neut", "轮子，自行车"),
    "wagen": ("A2", "NOUN", "Masc", "车辆，汽车，车厢"),
    "tier": ("A1", "NOUN", "Neut", "动物"),
    "hund": ("A1", "NOUN", "Masc", "狗"),
    "katze": ("A1", "NOUN", "Fem", "猫"),
    "wald": ("A2", "NOUN", "Masc", "森林，树林"),
    "see": ("A2", "NOUN", "Masc", "湖泊(der See) / 大海(die See)"),
    "meer": ("A2", "NOUN", "Neut", "大海，海洋"),
    "fluss": ("A2", "NOUN", "Masc", "河流，江河"),
    "berg": ("A2", "NOUN", "Masc", "山，高山"),
    "feld": ("A2", "NOUN", "Neut", "田野，领域"),
    "heim": ("A2", "NOUN", "Neut", "家园，宿舍，疗养院"),
    "hof": ("A2", "NOUN", "Masc", "院子，庭院，农庄"),
    "kreis": ("B1", "NOUN", "Masc", "圆，圈子，区，县"),
    "karte": ("A1", "NOUN", "Fem", "卡片，地图，菜单，门票"),
    "ausweis": ("A2", "NOUN", "Masc", "身份证件，证件"),
    "fahrt": ("A2", "NOUN", "Fem", "行程，行驶，旅途"),
    "flieger": ("A2", "NOUN", "Masc", "飞行员，飞机"),
    "flugzeug": ("A1", "NOUN", "Neut", "飞机"),
    "kraft": ("B1", "NOUN", "Fem", "力量，体力，效力"),
    "stoff": ("B1", "NOUN", "Masc", "物质，材料，布料"),
    "gas": ("A2", "NOUN", "Neut", "气体，煤气，天然气"),
    "öl": ("A2", "NOUN", "Neut", "油，石油，食用油"),
    "licht": ("A2", "NOUN", "Neut", "光线，灯光"),
    "feuer": ("A2", "NOUN", "Neut", "火，火焰，火灾"),
    "erde": ("A2", "NOUN", "Fem", "地球，土地，泥土"),
    "glas": ("A1", "NOUN", "Neut", "玻璃，玻璃杯"),
    "holz": ("A2", "NOUN", "Neut", "木材，木头"),
    "stein": ("A2", "NOUN", "Masc", "石头，岩石"),
    "gold": ("A2", "NOUN", "Neut", "黄金，金"),
    "silber": ("A2", "NOUN", "Neut", "白银，银"),
    "eisen": ("B1", "NOUN", "Neut", "铁，铁器"),
    "stahl": ("B1", "NOUN", "Masc", "钢铁，钢"),
    "kunst": ("A2", "NOUN", "Fem", "艺术，技能"),
    "sport": ("A1", "NOUN", "Masc", "体育，运动"),
    "ball": ("A1", "NOUN", "Masc", "球，舞会"),
    "netz": ("A2", "NOUN", "Neut", "网，网络"),
    "band": ("A2", "NOUN", "Neut", "带子，录音带；纽带"),
    "ring": ("A2", "NOUN", "Masc", "戒指，环，圈"),
    "hut": ("A1", "NOUN", "Masc", "帽子"),
    "mütze": ("A1", "NOUN", "Fem", "便帽，毛线帽"),
    "tasche": ("A1", "NOUN", "Fem", "口袋，包，提包"),
    "tuch": ("A2", "NOUN", "Neut", "布，手帕，巾"),
    "flasche": ("A1", "NOUN", "Fem", "瓶子"),
    "dose": ("A2", "NOUN", "Fem", "罐头，小盒子，插座"),
    "topf": ("A2", "NOUN", "Masc", "锅，壶"),
    "pfanne": ("A2", "NOUN", "Fem", "平底锅"),
    "messer": ("A1", "NOUN", "Neut", "刀，小刀"),
    "gabel": ("A1", "NOUN", "Fem", "叉子"),
    "löffel": ("A1", "NOUN", "Masc", "勺子，调羹"),
    "teller": ("A1", "NOUN", "Masc", "盘子，碟子"),
    "schrank": ("A1", "NOUN", "Masc", "柜子，衣柜"),
    "regal": ("A1", "NOUN", "Neut", "架子，书架"),
    "spiegel": ("A2", "NOUN", "Masc", "镜子"),
    "wand": ("A2", "NOUN", "Fem", "墙壁，隔板"),
    "mauer": ("A2", "NOUN", "Fem", "城墙，砖墙"),
    "dach": ("A2", "NOUN", "Neut", "屋顶，车顶"),
    "boden": ("A2", "NOUN", "Masc", "地面，地板，土地"),
    "schloss": ("A2", "NOUN", "Neut", "城堡，宫殿；锁"),
    "burg": ("A2", "NOUN", "Fem", "古堡，要塞"),
    "dorf": ("A2", "NOUN", "Neut", "村庄，乡村"),
    "reich": ("B1", "NOUN", "Neut", "帝国，王国，领域"),
    "park": ("A1", "NOUN", "Masc", "公园"),
    "gasse": ("A2", "NOUN", "Fem", "小巷，胡同"),
    "weg": ("A1", "NOUN", "Masc", "道路，途径，路线"),
    "brücke": ("A2", "NOUN", "Fem", "桥，桥梁"),
    "tunnel": ("A2", "NOUN", "Masc", "隧道"),
    "turm": ("A2", "NOUN", "Masc", "塔，钟楼"),
    "halle": ("A2", "NOUN", "Fem", "大厅，礼堂，车间"),
    "saal": ("A2", "NOUN", "Masc", "大厅，殿堂"),
    "hütte": ("A2", "NOUN", "Fem", "小屋，木屋，棚屋"),
    "fabrik": ("A2", "NOUN", "Fem", "工厂"),
    "lager": ("B1", "NOUN", "Neut", "仓库，营地，阵营"),
    "hafen": ("A2", "NOUN", "Masc", "港口，码头"),
    "geburt": ("A2", "NOUN", "Fem", "出生，诞生"),
    "liebe": ("A1", "NOUN", "Fem", "爱，爱情"),
    "kraftwerk": ("B1", "NOUN", "Neut", "发电厂，电站"),
    "schutzgesetz": ("B1", "NOUN", "Neut", "保护法"),
    "verkehrsmittel": ("A2", "NOUN", "Neut", "交通工具"),
    "lebensmittel": ("A1", "NOUN", "Neut", "食品，日常生鲜"),
    "sonnenbrille": ("A1", "NOUN", "Fem", "太阳镜，墨镜"),
    "brille": ("A1", "NOUN", "Fem", "眼镜"),
    "taschentuch": ("A1", "NOUN", "Neut", "纸巾，手帕"),
    "kindergarten": ("A1", "NOUN", "Masc", "幼儿园"),
    "studentenausweis": ("A2", "NOUN", "Masc", "学生证"),
    "haustür": ("A1", "NOUN", "Fem", "大门，进户门"),
    "bundeskanzler": ("B1", "NOUN", "Masc", "联邦总理"),
    "bundesregierung": ("B1", "NOUN", "Fem", "联邦政府"),
    "kanzler": ("B1", "NOUN", "Masc", "总理，首相"),
    "minister": ("B1", "NOUN", "Masc", "部长，大臣"),
    "ministerium": ("B1", "NOUN", "Neut", "部，政府部门"),
    "woche": ("A1", "NOUN", "Fem", "星期，周"),
    "monat": ("A1", "NOUN", "Masc", "月份，月"),
    "jahr": ("A1", "NOUN", "Neut", "年，年份"),
    "uhr": ("A1", "NOUN", "Fem", "时钟，手表，点钟"),
    "system": ("A2", "NOUN", "Neut", "系统，体制"),
    "energie": ("A2", "NOUN", "Fem", "能源，能量，精力"),
    "strom": ("A2", "NOUN", "Masc", "电力，电流，大河"),
    "krise": ("B1", "NOUN", "Fem", "危机"),
    "markt": ("A1", "NOUN", "Masc", "市场，集市"),
    "vertrag": ("A2", "NOUN", "Masc", "合同，契约"),
    "steuer": ("B1", "NOUN", "Fem", "税，税收"),
    "leistung": ("B1", "NOUN", "Fem", "成绩，效率，给付"),
    "erfolg": ("A2", "NOUN", "Masc", "成功，成就"),
    "angebot": ("A2", "NOUN", "Neut", "供应，报价，特价"),
    "nachfrage": ("B2", "NOUN", "Fem", "需求，询问"),
    "handel": ("B1", "NOUN", "Masc", "贸易，商业"),
    "industrie": ("B1", "NOUN", "Fem", "工业，产业"),
    "produktion": ("B1", "NOUN", "Fem", "生产，制作"),
    "nachricht": ("A1", "NOUN", "Fem", "消息，新闻"),
    "zeitung": ("A1", "NOUN", "Fem", "报纸"),
    "zeitschrift": ("A2", "NOUN", "Fem", "杂志，期刊"),
    "bericht": ("B1", "NOUN", "Masc", "报告，报道"),
    "forschung": ("B1", "NOUN", "Fem", "研究，科研"),
    "wissenschaft": ("B1", "NOUN", "Fem", "科学，学术"),
    "gesundheit": ("A1", "NOUN", "Fem", "健康"),
    "krankheit": ("A1", "NOUN", "Fem", "疾病"),
    "sicherheit": ("A2", "NOUN", "Fem", "安全，可靠性"),
    "kontrolle": ("A2", "NOUN", "Fem", "检查，控制"),
    "vorsorge": ("B1", "NOUN", "Fem", "预防，防范措施"),
    "versicherung": ("A2", "NOUN", "Fem", "保险，保证"),

    # ── Verb Stems used as First Elements in Compounds ───────────────────────
    "wohn": ("A1", "VERB", None, "居住，住宿"),
    "fahr": ("A1", "VERB", None, "驾驶，行驶，乘车"),
    "schlaf": ("A1", "VERB", None, "睡眠，睡觉"),
    "lese": ("A1", "VERB", None, "阅读，读"),
    "sprech": ("A1", "VERB", None, "说话，交谈"),
    "kauf": ("A1", "VERB", None, "购买，买"),
    "koch": ("A1", "VERB", None, "烹饪，做饭"),
    "back": ("A1", "VERB", None, "烘焙，烤"),
    "spar": ("A2", "VERB", None, "节约，储蓄"),
    "tank": ("A2", "VERB", None, "加油"),
    "lade": ("A2", "VERB", None, "装载，充电"),
    "lehr": ("A1", "VERB", None, "教学，教授"),
    "lern": ("A1", "VERB", None, "学习"),
    "druck": ("A2", "VERB", None, "打印，印刷"),
    "rechen": ("A2", "VERB", None, "计算，运算"),
    "such": ("A1", "VERB", None, "寻找，搜寻"),
    "prüf": ("A2", "VERB", None, "检查，测试"),

    # ── Adjective Stems used as First Elements in Compounds ───────────────────
    "hoch": ("A1", "ADJ", None, "高的，高级的"),
    "groß": ("A1", "ADJ", None, "大的，宏大的"),
    "klein": ("A1", "ADJ", None, "小的"),
    "alt": ("A1", "ADJ", None, "古老的，年老的"),
    "neu": ("A1", "ADJ", None, "新的"),
    "schwarz": ("A1", "ADJ", None, "黑色的"),
    "weiß": ("A1", "ADJ", None, "白色的"),
    "rot": ("A1", "ADJ", None, "红色的"),
    "blau": ("A1", "ADJ", None, "蓝色的"),
    "grün": ("A1", "ADJ", None, "绿色的"),
    "gelb": ("A1", "ADJ", None, "黄色的"),
    "voll": ("A1", "ADJ", None, "充满的，完整的"),
    "frei": ("A1", "ADJ", None, "自由的，空闲的"),
    "kurz": ("A1", "ADJ", None, "短的，简短的"),
    "lang": ("A1", "ADJ", None, "长的"),
    "warm": ("A1", "ADJ", None, "温暖的，热的"),
    "kalt": ("A1", "ADJ", None, "寒冷的，冷的"),
    "schnell": ("A1", "ADJ", None, "快的，迅速的"),
    "schwer": ("A1", "ADJ", None, "重的，难的"),
    "eigen": ("B1", "ADJ", None, "自己的，特有的"),
    "fremd": ("A2", "ADJ", None, "陌生的，外国的"),

    # ── Core Compounding Base Roots ──────────────────────────────────────────
    "maßnahme": ("B1", "NOUN", "Fem", "措施，办法"),
    "massnahme": ("B1", "NOUN", "Fem", "措施，办法"),
    "sprach": ("A1", "NOUN", "Fem", "语言"),
    "wirtschaft": ("B1", "NOUN", "Fem", "经济，经济学"),
    "bedingung": ("B1", "NOUN", "Fem", "条件，前提"),
}



def _get_element_info(token_lower: str) -> Optional[Dict[str, Any]]:
    """Retrieve morphology metadata from CORE_VOCAB_DB or LINGUISTICS_VOCAB_EXT."""
    k = token_lower.strip().lower()
    if not k:
        return None

    def _direct_lookup(term: str) -> Optional[Dict[str, Any]]:
        if term in CORE_VOCAB_DB:
            cefr, pos, gender, plural, def_zh = CORE_VOCAB_DB[term]
            return {
                "lemma": term,
                "pos": pos,
                "gender": gender,
                "def_zh": def_zh,
                "cefr": cefr,
                "source": "core_dict"
            }
        if term in LINGUISTICS_VOCAB_EXT:
            cefr, pos, gender, def_zh = LINGUISTICS_VOCAB_EXT[term]
            return {
                "lemma": term,
                "pos": pos,
                "gender": gender,
                "def_zh": def_zh,
                "cefr": cefr,
                "source": "linguistics_ext"
            }
        return None

    # 1. Direct hit
    hit = _direct_lookup(k)
    if hit:
        return hit

    # 2. ss <-> ß variations
    if "ss" in k:
        hit = _direct_lookup(k.replace("ss", "ß"))
        if hit:
            return hit
    if "ß" in k:
        hit = _direct_lookup(k.replace("ß", "ss"))
        if hit:
            return hit

    # 3. Known irregular plural stems
    plural_stems = {
        "wörter": "wort", "worte": "wort",
        "bücher": "buch",
        "männer": "mann",
        "frauen": "frau",
        "kinder": "kind",
        "häuser": "haus",
        "städte": "stadt",
        "länder": "land",
        "bäume": "baum",
        "tage": "tag",
        "bilder": "bild",
        "ärzte": "arzt",
        "züge": "zug",
        "hände": "hand",
        "mütter": "mutter",
        "väter": "vater",
        "brüder": "bruder",
        "töchter": "tochter"
    }
    if k in plural_stems:
        hit = _direct_lookup(plural_stems[k])
        if hit:
            return hit

    # 4. Standard German plural endings (-en, -n, -e, -er, -s)
    for suf in ["en", "n", "e", "er", "s"]:
        if k.endswith(suf) and len(k) > len(suf) + 2:
            stem = k[:-len(suf)]
            hit = _direct_lookup(stem) or _direct_lookup(stem.replace("ss", "ß"))
            if hit and hit.get("pos") == "NOUN":
                return hit

    return None


def lookup_linguistics_ext(lemma_or_word: str) -> Optional[Dict[str, Any]]:
    """查词链第 1.5 层：把 _get_element_info 的元数据包装成 lookup_core_vocab 同形 dict。

    为什么接线：LINGUISTICS_VOCAB_EXT（~200 词元）之前只被复合词拆分器用，
    主查词链从不查它，等于白存。这里复用 _get_element_info 自带的 ss/ß、变元音
    复数、名词后缀处理，key 规范化成 {lemma, cefr_level, pos, gender, plural,
    definition_zh, source}，与 core_dict.lookup_core_vocab 返回形状一致。
    """
    info = _get_element_info(lemma_or_word or "")
    if not info:
        return None
    return {
        "lemma": info.get("lemma", ""),
        "cefr_level": info.get("cefr", ""),
        "pos": info.get("pos", ""),
        "gender": info.get("gender"),
        "plural": "",
        "definition_zh": info.get("def_zh", ""),
        "source": "linguistics_ext",
    }




# ==============================================================================
# 3. German Compound Noun Splitter (Komposita-Zerlegung)
# ==============================================================================

# Valid German linking morphemes (Fugenelemente)
_FUGEN_ELEMENTS = ["", "s", "es", "en", "n", "er", "e"]


def split_komposita(word: str, min_part_len: int = 3) -> List[Dict[str, Any]]:
    """
    Recursively decomposes German compound nouns into constituent base morphemes.
    
    Rules & Constraints:
    - Minimum total word length >= 7.
    - Accurately identifies and strips Fugenelemente (-s-, -es-, -en-, -n-, -er-, -e-).
    - Requires each constituent part to be a recognized lexical morpheme (len >= min_part_len).
    - Returns a list of structured subword dicts:
      [{"word": sub_word, "lemma": lemma, "gender": gender, "def_zh": def_zh}, ...]
    - Returns an empty list [] if word is not a valid compound.
    """
    if not word or not isinstance(word, str):
        return []
    
    clean_word = word.strip()
    # German compounds to split should be at least 7 chars
    if len(clean_word) < 7:
        return []
    
    # Normalize to lowercase for segmentation
    norm_word = clean_word.lower()

    memo: Dict[str, List[List[Tuple[str, str, Dict[str, Any]]]]] = {}

    def _find_partitions(target: str) -> List[List[Tuple[str, str, Dict[str, Any]]]]:
        """Find all valid segmentations of target into list of (part_slice, fuge, info)."""
        if target in memo:
            return memo[target]
        
        results = []
        n = len(target)

        # Iterate possible first prefix lengths
        for i in range(min_part_len, n + 1):
            prefix = target[:i]
            info = _get_element_info(prefix)
            if not info:
                continue
            
            # Terminal condition: whole remainder is a single valid word
            if i == n:
                results.append([(prefix, "", info)])
                continue
            
            # Non-terminal: test each Fugenelement
            remainder = target[i:]
            for fuge in _FUGEN_ELEMENTS:
                if fuge and not remainder.startswith(fuge):
                    continue
                rem_after_fuge = remainder[len(fuge):]
                if len(rem_after_fuge) < min_part_len:
                    continue
                
                sub_partitions = _find_partitions(rem_after_fuge)
                for sp in sub_partitions:
                    results.append([(prefix, fuge, info)] + sp)

        memo[target] = results
        return results

    all_partitions = _find_partitions(norm_word)
    # Filter only multi-part segmentations (>= 2 parts)
    valid_compounds = [p for p in all_partitions if len(p) >= 2]
    
    if not valid_compounds:
        return []

    # Scoring algorithm to pick the most natural German morphological decomposition
    def _score_partition(partition: List[Tuple[str, str, Dict[str, Any]]]) -> float:
        score = 100.0
        
        # Reward solid morpheme decomposition (len >= 4)
        all_len_ok = all(len(p[0]) >= 4 for p in partition)
        if all_len_ok and len(partition) >= 2:
            score += 30.0
            
        # Penalize spurious tiny fragments (< 4 chars unless common like alt, rot, neu)
        short_count = sum(1 for p in partition if len(p[0]) < 4)
        score -= short_count * 25.0
        
        # Last element (Grundwort / Head Noun) must preferably be a NOUN
        last_info = partition[-1][2]
        if last_info.get("pos") == "NOUN":
            score += 30.0
        elif last_info.get("pos") in ("VERB", "ADJ"):
            score -= 10.0

        # First element (Bestimmungswort) prefer NOUN, then VERB/ADJ
        first_info = partition[0][2]
        if first_info.get("pos") == "NOUN":
            score += 20.0
        elif first_info.get("pos") in ("VERB", "ADJ"):
            score += 15.0

        for part_slice, fuge, info in partition:
            if len(part_slice) >= 4:
                score += 5.0
            if info.get("source") == "core_dict":
                score += 10.0
            # Fuge validity check
            if fuge == "s" and part_slice.endswith(("ung", "heit", "keit", "schaft", "ion", "tät", "tum", "utz", "tz")):
                score += 15.0

        return score


    best_partition = max(valid_compounds, key=_score_partition)

    # Format output list according to specification
    output: List[Dict[str, Any]] = []
    curr_idx = 0
    for idx, (part_slice, fuge, info) in enumerate(best_partition):
        # Extract matching casing from original word
        start_pos = curr_idx
        end_pos = curr_idx + len(part_slice)
        orig_slice = clean_word[start_pos:end_pos]
        curr_idx = end_pos + len(fuge)
        
        # Display title-cased for German noun parts
        display_word = orig_slice.capitalize() if info.get("pos") == "NOUN" else orig_slice
        
        output.append({
            "word": display_word,
            "lemma": info["lemma"],
            "gender": info.get("gender"),
            "def_zh": info.get("def_zh", "")
        })

    return output


# ==============================================================================
# 4. Präpositionen-Kollokationen（动词/形容词固定介词搭配）
# ==============================================================================
# 数据在 prep_dict.py（tools/build_prep.py 生成：人工 seed + AI 长尾）。
# try/except 照 core_dict.py 对 core_dict_ext 的先例：数据模块缺失时
# 功能降级为「没有搭配」，不阻断查词链。
try:
    from prep_dict import PREP_COLLOCATIONS
except ImportError:  # pragma: no cover - 只在数据集尚未生成时走到
    PREP_COLLOCATIONS = {}


def lookup_prep_collocations(lemma_or_word: str) -> List[Dict[str, str]]:
    """查固定介词搭配，返回 [{praeposition, kasus, bedeutung_zh, beispiel}]。

    一个词头可以有多个介词且意思不同（bestehen auf/aus/in），所以返回列表而非
    单值；没有搭配返回空列表（这是绝大多数词的正常结果，不是错误）。

    反身动词的键不带 sich（freuen），因为 spaCy 的 lemma 就是 freuen；
    「(sich)」标在中文义里。
    """
    key = (lemma_or_word or "").strip().lower()
    if not key:
        return []
    rows = PREP_COLLOCATIONS.get(key)
    if not rows:
        return []
    return [{"praeposition": r[0], "kasus": r[1], "bedeutung_zh": r[2], "beispiel": r[3]}
            for r in rows]
