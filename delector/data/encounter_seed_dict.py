# -*- coding: utf-8 -*-
"""预置遇见区卡包（encounter-pack/v1）—— 由离线脚本生成，请勿手工编辑。

来源（Source of Truth）
    delector/data/corpus_dict.py 的 OFFICIAL_CORPUS（A1–B2 真实分级德语短文）。

生成命令（Reproducible Command）
    export PYTHONIOENCODING=utf-8
    python tools/build_encounter_seed.py --levels A1,A2,B1 --created-at 2026-09-23

生成日期（Created At）
    2026-09-23

分级依据（Level Basis）
    estimated_cefr 直接取语料自带 cefr 字段（考纲权威分级）；
    不使用 vocab_stats 的启发式 level_hint 覆盖。

分析字段（Analysis）
    每包 analysis 由离线纯函数 delector.tools.vocab_stats.run 生成
    （考纲 A1∪A2 lemma 覆盖统计，无 DB/网络）；未知词频排名映射为 unknown_lemmas。
    analysis.lemma_seq 为逐 token lemma 序列，口径与 routes/encounter.py::_annotate_tokens
    同源（剔除 is_space 空白 token、保留标点 token），供前端在本机算覆盖率。

免责（Determinism & Immutability）
    本模块为纯数据：仅导出 PRESET_ENCOUNTER_PACKS，导入期零 spaCy、零网络、零副作用
    （项目红线 9）。内容由脚本确定性生成，同输入字节一致；
    **禁止手工改内容，改则重跑 tools/build_encounter_seed.py**。
"""
from typing import Any

# 预置卡包列表（encounter-pack/v1）。列表顺序 = pack_id 升序，保证确定性。
PRESET_ENCOUNTER_PACKS: list[dict[str, Any]] = [
    {
        "schema": "encounter-pack/v1",
        "pack_id": "seed-corpus-goethe_a1_alltag_01",
        "estimated_cefr": "A1",
        "analysis": {
            "tokens_total": 59,
            "known_count": 37,
            "known_rate": 0.627,
            "unknown_lemmas": [
                {
                    "lemma": "--",
                    "count": 7
                },
                {
                    "lemma": "der",
                    "count": 5
                },
                {
                    "lemma": "ein",
                    "count": 3
                },
                {
                    "lemma": "äpfel",
                    "count": 2
                },
                {
                    "lemma": "marktplatz",
                    "count": 1
                },
                {
                    "lemma": "müller",
                    "count": 1
                },
                {
                    "lemma": "pfund",
                    "count": 1
                },
                {
                    "lemma": "wochenende",
                    "count": 1
                },
                {
                    "lemma": "wochenmarkt",
                    "count": 1
                }
            ],
            "level_hint": "B1",
            "lemma_seq": [
                "jeder",
                "Samstag",
                "geben",
                "es",
                "ein",
                "groß",
                "Wochenmarkt",
                "auf",
                "der",
                "Marktplatz",
                "vor",
                "der",
                "Rathaus",
                "--",
                "der",
                "Mensch",
                "kaufen",
                "dort",
                "frisch",
                "Obst",
                "--",
                "Gemüse",
                "--",
                "Brot",
                "und",
                "Käse",
                "--",
                "Frau",
                "Müller",
                "kaufen",
                "heute",
                "zwei",
                "Kilo",
                "Äpfel",
                "und",
                "ein",
                "Pfund",
                "Tomate",
                "--",
                "der",
                "Äpfel",
                "schmecken",
                "süß",
                "und",
                "sein",
                "nicht",
                "teuer",
                "--",
                "der",
                "Verkäufer",
                "sein",
                "sehr",
                "freundlich",
                "und",
                "wünschen",
                "ein",
                "schön",
                "Wochenende",
                "--"
            ]
        },
        "glosses": [],
        "article": {
            "title": "Ein Tag auf dem Wochenmarkt",
            "raw_text": "Jeden Samstag gibt es einen großen Wochenmarkt auf dem Marktplatz vor dem Rathaus. Die Menschen kaufen dort frisches Obst, Gemüse, Brot und Käse. Frau Müller kauft heute zwei Kilo Äpfel und ein Pfund Tomaten. Die Äpfel schmecken süß und sind nicht teuer. Der Verkäufer ist sehr freundlich und wünscht ein schönes Wochenende."
        }
    },
    {
        "schema": "encounter-pack/v1",
        "pack_id": "seed-corpus-goethe_a1_campus_02",
        "estimated_cefr": "A1",
        "analysis": {
            "tokens_total": 54,
            "known_count": 34,
            "known_rate": 0.63,
            "unknown_lemmas": [
                {
                    "lemma": "--",
                    "count": 6
                },
                {
                    "lemma": "der",
                    "count": 3
                },
                {
                    "lemma": "deutsch",
                    "count": 1
                },
                {
                    "lemma": "ein",
                    "count": 1
                },
                {
                    "lemma": "grammatikübung",
                    "count": 1
                },
                {
                    "lemma": "ich",
                    "count": 1
                },
                {
                    "lemma": "mein",
                    "count": 1
                },
                {
                    "lemma": "mir",
                    "count": 1
                },
                {
                    "lemma": "unser",
                    "count": 1
                },
                {
                    "lemma": "vieler",
                    "count": 1
                },
                {
                    "lemma": "volkshochschule",
                    "count": 1
                },
                {
                    "lemma": "wagner",
                    "count": 1
                },
                {
                    "lemma": "wir",
                    "count": 1
                }
            ],
            "level_hint": "B1",
            "lemma_seq": [
                "ich",
                "besuchen",
                "seit",
                "drei",
                "Woche",
                "ein",
                "Deutschkurs",
                "an",
                "der",
                "Volkshochschule",
                "--",
                "der",
                "Unterricht",
                "beginnen",
                "jeder",
                "Dienstag",
                "und",
                "Donnerstag",
                "um",
                "achtzehn",
                "Uhr",
                "--",
                "in",
                "mein",
                "Gruppe",
                "lernen",
                "zwölf",
                "Person",
                "aus",
                "verschieden",
                "Land",
                "--",
                "unser",
                "Lehrer",
                "heißen",
                "Herr",
                "Wagner",
                "--",
                "wir",
                "machen",
                "vieler",
                "Grammatikübung",
                "und",
                "sprechen",
                "zusammen",
                "Deutsch",
                "--",
                "der",
                "lernen",
                "machen",
                "mir",
                "groß",
                "Spaß",
                "--"
            ]
        },
        "glosses": [],
        "article": {
            "title": "Mein Deutschkurs an der Volkshochschule",
            "raw_text": "Ich besuche seit drei Wochen einen Deutschkurs an der Volkshochschule. Der Unterricht beginnt jeden Dienstag und Donnerstag um achtzehn Uhr. In meiner Gruppe lernen zwölf Personen aus verschiedenen Ländern. Unser Lehrer heißt Herr Wagner. Wir machen viele Grammatikübungen und sprechen zusammen Deutsch. Das Lernen macht mir großen Spaß."
        }
    },
    {
        "schema": "encounter-pack/v1",
        "pack_id": "seed-corpus-goethe_a2_alltag_03",
        "estimated_cefr": "A2",
        "analysis": {
            "tokens_total": 92,
            "known_count": 50,
            "known_rate": 0.543,
            "unknown_lemmas": [
                {
                    "lemma": "--",
                    "count": 12
                },
                {
                    "lemma": "ein",
                    "count": 4
                },
                {
                    "lemma": "ich",
                    "count": 4
                },
                {
                    "lemma": "euch",
                    "count": 3
                },
                {
                    "lemma": "der",
                    "count": 2
                },
                {
                    "lemma": "mein",
                    "count": 2
                },
                {
                    "lemma": "bereits",
                    "count": 1
                },
                {
                    "lemma": "besonderer",
                    "count": 1
                },
                {
                    "lemma": "dessert",
                    "count": 1
                },
                {
                    "lemma": "dieser",
                    "count": 1
                },
                {
                    "lemma": "fangen",
                    "count": 1
                },
                {
                    "lemma": "gemütlich",
                    "count": 1
                },
                {
                    "lemma": "gerne",
                    "count": 1
                },
                {
                    "lemma": "grillabend",
                    "count": 1
                },
                {
                    "lemma": "ihr",
                    "count": 1
                },
                {
                    "lemma": "mir",
                    "count": 1
                },
                {
                    "lemma": "nächster",
                    "count": 1
                },
                {
                    "lemma": "ob",
                    "count": 1
                },
                {
                    "lemma": "sorgen",
                    "count": 1
                },
                {
                    "lemma": "stadtpark",
                    "count": 1
                },
                {
                    "lemma": "würstchen",
                    "count": 1
                }
            ],
            "level_hint": "B1",
            "lemma_seq": [
                "lieb",
                "Freund",
                "--",
                "nächster",
                "Woche",
                "an",
                "Samstag",
                "werden",
                "ich",
                "dreißig",
                "Jahr",
                "alt",
                "--",
                "dieser",
                "besonderer",
                "Tag",
                "möchten",
                "ich",
                "gerne",
                "mit",
                "euch",
                "feiern",
                "--",
                "ich",
                "laden",
                "euch",
                "herzlich",
                "zu",
                "ein",
                "gemütlich",
                "Grillabend",
                "in",
                "mein",
                "Garten",
                "ein",
                "--",
                "der",
                "Feier",
                "fangen",
                "um",
                "neunzehn",
                "Uhr",
                "an",
                "--",
                "für",
                "Getränk",
                "--",
                "Fleisch",
                "und",
                "Würstchen",
                "haben",
                "ich",
                "bereits",
                "sorgen",
                "--",
                "es",
                "sein",
                "toll",
                "--",
                "wenn",
                "jeder",
                "von",
                "euch",
                "ein",
                "klein",
                "Salat",
                "oder",
                "ein",
                "Dessert",
                "mitbringen",
                "können",
                "--",
                "mein",
                "Haus",
                "liegen",
                "direkt",
                "neben",
                "der",
                "Stadtpark",
                "--",
                "bitte",
                "geben",
                "mir",
                "bis",
                "Mittwoch",
                "Bescheid",
                "--",
                "ob",
                "ihr",
                "kommen",
                "können",
                "--"
            ]
        },
        "glosses": [],
        "article": {
            "title": "Eine Einladung zur Geburtstagsfeier",
            "raw_text": "Liebe Freunde, nächste Woche am Samstag werde ich dreißig Jahre alt! Diesen besonderen Tag möchte ich gerne mit euch feiern. Ich lade euch herzlich zu einem gemütlichen Grillabend in meinen Garten ein. Die Feier fängt um neunzehn Uhr an. Für Getränke, Fleisch und Würstchen habe ich bereits gesorgt. Es wäre toll, wenn jeder von euch einen kleinen Salat oder ein Dessert mitbringen könnte. Mein Haus liegt direkt neben dem Stadtpark. Bitte gebt mir bis Mittwoch Bescheid, ob ihr kommen könnt."
        }
    },
    {
        "schema": "encounter-pack/v1",
        "pack_id": "seed-corpus-goethe_a2_kultur_04",
        "estimated_cefr": "A2",
        "analysis": {
            "tokens_total": 76,
            "known_count": 36,
            "known_rate": 0.474,
            "unknown_lemmas": [
                {
                    "lemma": "--",
                    "count": 8
                },
                {
                    "lemma": "der",
                    "count": 7
                },
                {
                    "lemma": "wir",
                    "count": 4
                },
                {
                    "lemma": "bayerisch",
                    "count": 1
                },
                {
                    "lemma": "biergarten",
                    "count": 1
                },
                {
                    "lemma": "danach",
                    "count": 1
                },
                {
                    "lemma": "deutsch",
                    "count": 1
                },
                {
                    "lemma": "ein",
                    "count": 1
                },
                {
                    "lemma": "eisbachwelle",
                    "count": 1
                },
                {
                    "lemma": "englisch",
                    "count": 1
                },
                {
                    "lemma": "glockenspiel",
                    "count": 1
                },
                {
                    "lemma": "hervorragend",
                    "count": 1
                },
                {
                    "lemma": "letzter",
                    "count": 1
                },
                {
                    "lemma": "marienplatz",
                    "count": 1
                },
                {
                    "lemma": "münchen",
                    "count": 1
                },
                {
                    "lemma": "nachmittag",
                    "count": 1
                },
                {
                    "lemma": "samstagvormittag",
                    "count": 1
                },
                {
                    "lemma": "spazieren",
                    "count": 1
                },
                {
                    "lemma": "surfer",
                    "count": 1
                },
                {
                    "lemma": "technik",
                    "count": 1
                },
                {
                    "lemma": "uns",
                    "count": 1
                },
                {
                    "lemma": "wissenschaft",
                    "count": 1
                },
                {
                    "lemma": "wochenende",
                    "count": 1
                },
                {
                    "lemma": "zuschauen",
                    "count": 1
                }
            ],
            "level_hint": "B1",
            "lemma_seq": [
                "letzter",
                "Wochenende",
                "haben",
                "wir",
                "ein",
                "kurz",
                "Reise",
                "nach",
                "München",
                "machen",
                "--",
                "an",
                "Samstagvormittag",
                "sein",
                "wir",
                "durch",
                "der",
                "englisch",
                "Garten",
                "spazieren",
                "und",
                "haben",
                "der",
                "Surfer",
                "auf",
                "der",
                "Eisbachwelle",
                "zuschauen",
                "--",
                "danach",
                "besuchen",
                "wir",
                "der",
                "Marienplatz",
                "--",
                "um",
                "der",
                "berühmt",
                "Glockenspiel",
                "an",
                "neu",
                "Rathaus",
                "zu",
                "sehen",
                "--",
                "an",
                "Nachmittag",
                "sein",
                "wir",
                "in",
                "deutsch",
                "Museum",
                "--",
                "weil",
                "uns",
                "Technik",
                "und",
                "Wissenschaft",
                "sehr",
                "interessieren",
                "--",
                "der",
                "Wetter",
                "sein",
                "sonnig",
                "--",
                "und",
                "der",
                "bayerisch",
                "Küche",
                "in",
                "biergarten",
                "haben",
                "hervorragend",
                "schmecken",
                "--"
            ]
        },
        "glosses": [],
        "article": {
            "title": "Ein Wochenende in München",
            "raw_text": "Letztes Wochenende haben wir eine kurze Reise nach München gemacht. Am Samstagvormittag sind wir durch den Englischen Garten spaziert und haben den Surfern auf der Eisbachwelle zugeschaut. Danach besuchten wir den Marienplatz, um das berühmte Glockenspiel am Neuen Rathaus zu sehen. Am Nachmittag waren wir im Deutschen Museum, weil uns Technik und Wissenschaft sehr interessieren. Das Wetter war sonnig, und die bayerische Küche im Biergarten hat hervorragend geschmeckt."
        }
    },
    {
        "schema": "encounter-pack/v1",
        "pack_id": "seed-corpus-goethe_b1_beruf_06",
        "estimated_cefr": "B1",
        "analysis": {
            "tokens_total": 101,
            "known_count": 45,
            "known_rate": 0.446,
            "unknown_lemmas": [
                {
                    "lemma": "--",
                    "count": 10
                },
                {
                    "lemma": "der",
                    "count": 5
                },
                {
                    "lemma": "ein",
                    "count": 2
                },
                {
                    "lemma": "vieler",
                    "count": 2
                },
                {
                    "lemma": "abschalten",
                    "count": 1
                },
                {
                    "lemma": "arbeitnehmer",
                    "count": 1
                },
                {
                    "lemma": "arbeitsplatz",
                    "count": 1
                },
                {
                    "lemma": "bedeutung",
                    "count": 1
                },
                {
                    "lemma": "belegen",
                    "count": 1
                },
                {
                    "lemma": "beruflich",
                    "count": 1
                },
                {
                    "lemma": "berufsverkehr",
                    "count": 1
                },
                {
                    "lemma": "beschäftigter",
                    "count": 1
                },
                {
                    "lemma": "dieser",
                    "count": 1
                },
                {
                    "lemma": "erfordern",
                    "count": 1
                },
                {
                    "lemma": "etablieren",
                    "count": 1
                },
                {
                    "lemma": "feierabend",
                    "count": 1
                },
                {
                    "lemma": "flexibel",
                    "count": 1
                },
                {
                    "lemma": "gestalten",
                    "count": 1
                },
                {
                    "lemma": "gleichzeitig",
                    "count": 1
                },
                {
                    "lemma": "grund",
                    "count": 1
                },
                {
                    "lemma": "heimarbeit",
                    "count": 1
                },
                {
                    "lemma": "homeoffice",
                    "count": 1
                },
                {
                    "lemma": "hybrid",
                    "count": 1
                },
                {
                    "lemma": "ihr",
                    "count": 1
                },
                {
                    "lemma": "konzentriert",
                    "count": 1
                },
                {
                    "lemma": "mancher",
                    "count": 1
                },
                {
                    "lemma": "maß",
                    "count": 1
                },
                {
                    "lemma": "modell",
                    "count": 1
                },
                {
                    "lemma": "möglichkeit",
                    "count": 1
                },
                {
                    "lemma": "privatem",
                    "count": 1
                },
                {
                    "lemma": "präsenztag",
                    "count": 1
                },
                {
                    "lemma": "schätzen",
                    "count": 1
                },
                {
                    "lemma": "selbstdisziplin",
                    "count": 1
                },
                {
                    "lemma": "sofern",
                    "count": 1
                },
                {
                    "lemma": "studie",
                    "count": 1
                },
                {
                    "lemma": "tagesablauf",
                    "count": 1
                },
                {
                    "lemma": "trennen",
                    "count": 1
                },
                {
                    "lemma": "täglich",
                    "count": 1
                },
                {
                    "lemma": "vergangen",
                    "count": 1
                },
                {
                    "lemma": "vermeiden",
                    "count": 1
                },
                {
                    "lemma": "vorhanden",
                    "count": 1
                }
            ],
            "level_hint": "B1",
            "lemma_seq": [
                "der",
                "arbeiten",
                "von",
                "zu",
                "Haus",
                "aus",
                "haben",
                "in",
                "der",
                "vergangen",
                "Jahr",
                "stark",
                "an",
                "Bedeutung",
                "gewinnen",
                "--",
                "vieler",
                "Arbeitnehmer",
                "schätzen",
                "der",
                "Möglichkeit",
                "--",
                "ihr",
                "Tagesablauf",
                "flexibel",
                "zu",
                "gestalten",
                "und",
                "der",
                "täglich",
                "Weg",
                "zu",
                "Arbeit",
                "in",
                "Berufsverkehr",
                "zu",
                "vermeiden",
                "--",
                "Studie",
                "belegen",
                "--",
                "dass",
                "Mitarbeiter",
                "in",
                "Homeoffice",
                "oft",
                "konzentriert",
                "arbeiten",
                "können",
                "--",
                "sofern",
                "ein",
                "ruhig",
                "Arbeitsplatz",
                "vorhanden",
                "sein",
                "--",
                "gleichzeitig",
                "erfordern",
                "der",
                "Heimarbeit",
                "ein",
                "hoch",
                "Maß",
                "an",
                "Selbstdisziplin",
                "--",
                "es",
                "fallen",
                "mancher",
                "beschäftigter",
                "schwer",
                "--",
                "nach",
                "Feierabend",
                "abschalten",
                "und",
                "Beruflich",
                "von",
                "Privatem",
                "klar",
                "zu",
                "trennen",
                "--",
                "aus",
                "dieser",
                "Grund",
                "etablieren",
                "vieler",
                "modern",
                "Unternehmen",
                "hybrid",
                "Modell",
                "mit",
                "zwei",
                "bis",
                "drei",
                "Präsenztag",
                "pro",
                "Woche",
                "--"
            ]
        },
        "glosses": [],
        "article": {
            "title": "Homeoffice und flexible Arbeitszeiten",
            "raw_text": "Das Arbeiten von zu Hause aus hat in den vergangenen Jahren stark an Bedeutung gewonnen. Viele Arbeitnehmer schätzen die Möglichkeit, ihren Tagesablauf flexibler zu gestalten und den täglichen Weg zur Arbeit im Berufsverkehr zu vermeiden. Studien belegen, dass Mitarbeiter im Homeoffice oft konzentrierter arbeiten können, sofern ein ruhiger Arbeitsplatz vorhanden ist. Gleichzeitig erfordert die Heimarbeit ein hohes Maß an Selbstdisziplin. Es fällt manchen Beschäftigten schwer, nach Feierabend abzuschalten und Berufliches von Privatem klar zu trennen. Aus diesem Grund etablieren viele moderne Unternehmen hybride Modelle mit zwei bis drei Präsenztagen pro Woche."
        }
    },
    {
        "schema": "encounter-pack/v1",
        "pack_id": "seed-corpus-goethe_b1_campus_05",
        "estimated_cefr": "B1",
        "analysis": {
            "tokens_total": 99,
            "known_count": 50,
            "known_rate": 0.505,
            "unknown_lemmas": [
                {
                    "lemma": "--",
                    "count": 10
                },
                {
                    "lemma": "der",
                    "count": 5
                },
                {
                    "lemma": "ein",
                    "count": 2
                },
                {
                    "lemma": "sich",
                    "count": 2
                },
                {
                    "lemma": "aller",
                    "count": 1
                },
                {
                    "lemma": "allerdings",
                    "count": 1
                },
                {
                    "lemma": "bereits",
                    "count": 1
                },
                {
                    "lemma": "deutschland",
                    "count": 1
                },
                {
                    "lemma": "einiger",
                    "count": 1
                },
                {
                    "lemma": "enthalten",
                    "count": 1
                },
                {
                    "lemma": "entscheiden",
                    "count": 1
                },
                {
                    "lemma": "entscheidend",
                    "count": 1
                },
                {
                    "lemma": "erster",
                    "count": 1
                },
                {
                    "lemma": "gegenseitig",
                    "count": 1
                },
                {
                    "lemma": "herausforderung",
                    "count": 1
                },
                {
                    "lemma": "häufig",
                    "count": 1
                },
                {
                    "lemma": "knüpfen",
                    "count": 1
                },
                {
                    "lemma": "kommiliton",
                    "count": 1
                },
                {
                    "lemma": "privatsphär",
                    "count": 1
                },
                {
                    "lemma": "putzplan",
                    "count": 1
                },
                {
                    "lemma": "rücksichtnahme",
                    "count": 1
                },
                {
                    "lemma": "semester",
                    "count": 1
                },
                {
                    "lemma": "strom",
                    "count": 1
                },
                {
                    "lemma": "studentenwohnheim",
                    "count": 1
                },
                {
                    "lemma": "studienanfänger",
                    "count": 1
                },
                {
                    "lemma": "ungestört",
                    "count": 1
                },
                {
                    "lemma": "unverzichtbar",
                    "count": 1
                },
                {
                    "lemma": "vieler",
                    "count": 1
                },
                {
                    "lemma": "vorteil",
                    "count": 1
                },
                {
                    "lemma": "wahl",
                    "count": 1
                },
                {
                    "lemma": "warmmiete",
                    "count": 1
                },
                {
                    "lemma": "wohngemeinschaft",
                    "count": 1
                },
                {
                    "lemma": "zudem",
                    "count": 1
                },
                {
                    "lemma": "zusammenleben",
                    "count": 1
                }
            ],
            "level_hint": "B1",
            "lemma_seq": [
                "für",
                "vieler",
                "Studienanfänger",
                "in",
                "Deutschland",
                "sein",
                "der",
                "Studentenwohnheim",
                "der",
                "erster",
                "Wahl",
                "--",
                "der",
                "entscheidend",
                "Vorteil",
                "liegen",
                "in",
                "der",
                "günstig",
                "Warmmiete",
                "--",
                "da",
                "Strom",
                "--",
                "Heizung",
                "und",
                "Internet",
                "bereits",
                "in",
                "Preis",
                "enthalten",
                "sein",
                "--",
                "zudem",
                "knüpfen",
                "man",
                "in",
                "ein",
                "Wohngemeinschaft",
                "schnell",
                "neu",
                "Kontakt",
                "mit",
                "Kommiliton",
                "aus",
                "aller",
                "Welt",
                "--",
                "allerdings",
                "bringen",
                "der",
                "zusammenleben",
                "auf",
                "eng",
                "Raum",
                "auch",
                "Herausforderung",
                "mit",
                "sich",
                "--",
                "da",
                "Küche",
                "und",
                "Bad",
                "oft",
                "teilen",
                "werden",
                "müssen",
                "--",
                "sein",
                "fest",
                "Putzplan",
                "und",
                "gegenseitig",
                "Rücksichtnahme",
                "unverzichtbar",
                "--",
                "wer",
                "viel",
                "Ruhe",
                "zu",
                "lernen",
                "und",
                "ungestört",
                "Privatsphär",
                "suchen",
                "--",
                "entscheiden",
                "sich",
                "nach",
                "einiger",
                "Semester",
                "häufig",
                "für",
                "ein",
                "eigen",
                "klein",
                "Wohnung",
                "--"
            ]
        },
        "glosses": [],
        "article": {
            "title": "Wohnen im Studentenwohnheim: Vor- und Nachteile",
            "raw_text": "Für viele Studienanfänger in Deutschland ist das Studentenwohnheim die erste Wahl. Der entscheidende Vorteil liegt in der günstigen Warmmiete, da Strom, Heizung und Internet bereits im Preis enthalten sind. Zudem knüpft man in einer Wohngemeinschaft schnell neue Kontakte mit Kommilitonen aus aller Welt. Allerdings bringt das Zusammenleben auf engem Raum auch Herausforderungen mit sich. Da Küche und Bad oft geteilt werden müssen, sind feste Putzpläne und gegenseitige Rücksichtnahme unverzichtbar. Wer viel Ruhe zum Lernen und ungestörte Privatsphäre sucht, entscheidet sich nach einigen Semestern häufig für eine eigene kleine Wohnung."
        }
    },
    {
        "schema": "encounter-pack/v1",
        "pack_id": "seed-corpus-goethe_b1_kultur_07",
        "estimated_cefr": "B1",
        "analysis": {
            "tokens_total": 95,
            "known_count": 34,
            "known_rate": 0.358,
            "unknown_lemmas": [
                {
                    "lemma": "der",
                    "count": 11
                },
                {
                    "lemma": "--",
                    "count": 7
                },
                {
                    "lemma": "deutsch",
                    "count": 2
                },
                {
                    "lemma": "abschluss",
                    "count": 1
                },
                {
                    "lemma": "absolvent",
                    "count": 1
                },
                {
                    "lemma": "anderer",
                    "count": 1
                },
                {
                    "lemma": "ausbildungssystem",
                    "count": 1
                },
                {
                    "lemma": "ausbildungsvergütung",
                    "count": 1
                },
                {
                    "lemma": "auszubildende",
                    "count": 1
                },
                {
                    "lemma": "beitragen",
                    "count": 1
                },
                {
                    "lemma": "berufsschule",
                    "count": 1
                },
                {
                    "lemma": "betrieb",
                    "count": 1
                },
                {
                    "lemma": "betriebspraxis",
                    "count": 1
                },
                {
                    "lemma": "bildungsexpert",
                    "count": 1
                },
                {
                    "lemma": "dabei",
                    "count": 1
                },
                {
                    "lemma": "dazu",
                    "count": 1
                },
                {
                    "lemma": "dieser",
                    "count": 1
                },
                {
                    "lemma": "dreieinhalb",
                    "count": 1
                },
                {
                    "lemma": "dual",
                    "count": 1
                },
                {
                    "lemma": "ein",
                    "count": 1
                },
                {
                    "lemma": "einer",
                    "count": 1
                },
                {
                    "lemma": "einsetzbar",
                    "count": 1
                },
                {
                    "lemma": "europäisch",
                    "count": 1
                },
                {
                    "lemma": "fachwiss",
                    "count": 1
                },
                {
                    "lemma": "gelten",
                    "count": 1
                },
                {
                    "lemma": "grundlage",
                    "count": 1
                },
                {
                    "lemma": "ihr",
                    "count": 1
                },
                {
                    "lemma": "jugendarbeitslosigkeit",
                    "count": 1
                },
                {
                    "lemma": "loben",
                    "count": 1
                },
                {
                    "lemma": "maßgeblich",
                    "count": 1
                },
                {
                    "lemma": "modell",
                    "count": 1
                },
                {
                    "lemma": "monatlich",
                    "count": 1
                },
                {
                    "lemma": "niedrig",
                    "count": 1
                },
                {
                    "lemma": "regel",
                    "count": 1
                },
                {
                    "lemma": "regelmäßig",
                    "count": 1
                },
                {
                    "lemma": "sowohl",
                    "count": 1
                },
                {
                    "lemma": "system",
                    "count": 1
                },
                {
                    "lemma": "säule",
                    "count": 1
                },
                {
                    "lemma": "theoretisch",
                    "count": 1
                },
                {
                    "lemma": "tragend",
                    "count": 1
                },
                {
                    "lemma": "vergleich",
                    "count": 1
                },
                {
                    "lemma": "vergüten",
                    "count": 1
                },
                {
                    "lemma": "verknüpfung",
                    "count": 1
                },
                {
                    "lemma": "wirtschaft",
                    "count": 1
                }
            ],
            "level_hint": "B1",
            "lemma_seq": [
                "der",
                "dual",
                "Ausbildungssystem",
                "gelten",
                "als",
                "einer",
                "der",
                "tragend",
                "Säule",
                "der",
                "deutsch",
                "Wirtschaft",
                "--",
                "Auszubildende",
                "lernen",
                "dabei",
                "sowohl",
                "der",
                "theoretisch",
                "Grundlage",
                "in",
                "der",
                "Berufsschule",
                "als",
                "auch",
                "der",
                "praktisch",
                "Arbeit",
                "direkt",
                "in",
                "Betrieb",
                "--",
                "dieser",
                "Modell",
                "dauern",
                "in",
                "der",
                "Regel",
                "zwischen",
                "zwei",
                "und",
                "dreieinhalb",
                "Jahr",
                "und",
                "werden",
                "mit",
                "ein",
                "monatlich",
                "Ausbildungsvergütung",
                "vergüten",
                "--",
                "durch",
                "der",
                "eng",
                "Verknüpfung",
                "von",
                "Fachwiss",
                "und",
                "Betriebspraxis",
                "sein",
                "der",
                "Absolvent",
                "nach",
                "ihr",
                "Abschluss",
                "sofort",
                "voll",
                "einsetzbar",
                "--",
                "international",
                "Bildungsexpert",
                "loben",
                "der",
                "deutsch",
                "System",
                "regelmäßig",
                "--",
                "da",
                "es",
                "maßgeblich",
                "dazu",
                "beitragen",
                "--",
                "der",
                "Jugendarbeitslosigkeit",
                "in",
                "Vergleich",
                "zu",
                "anderer",
                "europäisch",
                "Land",
                "niedrig",
                "zu",
                "halten",
                "--"
            ]
        },
        "glosses": [],
        "article": {
            "title": "Die duale Berufsausbildung in Deutschland",
            "raw_text": "Das duale Ausbildungssystem gilt als eine der tragenden Säulen der deutschen Wirtschaft. Auszubildende lernen dabei sowohl die theoretischen Grundlagen in der Berufsschule als auch die praktische Arbeit direkt im Betrieb. Dieses Modell dauert in der Regel zwischen zwei und dreieinhalb Jahren und wird mit einer monatlichen Ausbildungsvergütung vergütet. Durch die enge Verknüpfung von Fachwissen und Betriebspraxis sind die Absolventen nach ihrem Abschluss sofort voll einsetzbar. Internationale Bildungsexperten loben das deutsche System regelmäßig, da es maßgeblich dazu beiträgt, die Jugendarbeitslosigkeit im Vergleich zu anderen europäischen Ländern niedrig zu halten."
        }
    }
]
