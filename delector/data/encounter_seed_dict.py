# -*- coding: utf-8 -*-
"""预置遇见区卡包（encounter-pack/v1）—— 由离线脚本生成，请勿手工编辑。

来源（Source of Truth）
    delector/data/corpus_dict.py 的 OFFICIAL_CORPUS（A1–B2 真实分级德语短文）。

生成命令（Reproducible Command）
    export PYTHONIOENCODING=utf-8
    python tools/build_encounter_seed.py --levels A1,A2 --created-at 2026-09-10

生成日期（Created At）
    2026-09-10

分级依据（Level Basis）
    estimated_cefr 直接取语料自带 cefr 字段（考纲权威分级）；
    不使用 vocab_stats 的启发式 level_hint 覆盖。

分析字段（Analysis）
    每包 analysis 由离线纯函数 delector.tools.vocab_stats.run 生成
    （考纲 A1∪A2 lemma 覆盖统计，无 DB/网络）；未知词频排名映射为 unknown_lemmas。

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
                    "lemma": "rathaus",
                    "count": 1
                },
                {
                    "lemma": "wochenmarkt",
                    "count": 1
                }
            ],
            "level_hint": "B1"
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
            "known_count": 32,
            "known_rate": 0.593,
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
                    "lemma": "uhr",
                    "count": 1
                },
                {
                    "lemma": "unser",
                    "count": 1
                },
                {
                    "lemma": "verschieden",
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
            "level_hint": "B1"
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
            "known_count": 51,
            "known_rate": 0.554,
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
                    "lemma": "bescheid",
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
                    "lemma": "gerne",
                    "count": 1
                },
                {
                    "lemma": "grillabend",
                    "count": 1
                },
                {
                    "lemma": "herzlich",
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
                    "lemma": "stadtpark",
                    "count": 1
                },
                {
                    "lemma": "uhr",
                    "count": 1
                },
                {
                    "lemma": "würstchen",
                    "count": 1
                }
            ],
            "level_hint": "B1"
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
                    "lemma": "berühmt",
                    "count": 1
                },
                {
                    "lemma": "biergarten",
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
                    "lemma": "kurz",
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
                    "lemma": "rathaus",
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
                    "lemma": "uns",
                    "count": 1
                },
                {
                    "lemma": "wissenschaft",
                    "count": 1
                },
                {
                    "lemma": "zuschauen",
                    "count": 1
                }
            ],
            "level_hint": "B1"
        },
        "glosses": [],
        "article": {
            "title": "Ein Wochenende in München",
            "raw_text": "Letztes Wochenende haben wir eine kurze Reise nach München gemacht. Am Samstagvormittag sind wir durch den Englischen Garten spaziert und haben den Surfern auf der Eisbachwelle zugeschaut. Danach besuchten wir den Marienplatz, um das berühmte Glockenspiel am Neuen Rathaus zu sehen. Am Nachmittag waren wir im Deutschen Museum, weil uns Technik und Wissenschaft sehr interessieren. Das Wetter war sonnig, und die bayerische Küche im Biergarten hat hervorragend geschmeckt."
        }
    }
]
