"""
DeLector - Goethe-Zertifikat A1 Hörverstehen (Listening) Exam Dataset & Engine
Contains 5 authentic Goethe A1 model test sets (15 questions per set, 75 questions total).
Teil 1: 6 questions (A/B/C, repeated 2 times)
Teil 2: 4 questions (Richtig/Falsch, repeated 1 time)
Teil 3: 5 questions (A/B/C, repeated 2 times)
"""

from typing import List, Dict, Any, Optional

# ─────────────────────────────────────────────────────────────────────────────
# 5 Full A1 Listening Exam Sets (Modellsatz 01 - 05)
# ─────────────────────────────────────────────────────────────────────────────

A1_HOEREN_SETS: List[Dict[str, Any]] = [
    # ── SET 01 ──────────────────────────────────────────────────────────────
    {
        "set_id": 1,
        "title_de": "Goethe-Zertifikat A1 Modellsatz 01",
        "title_zh": "歌德 A1 官方全真模考卷 01",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_h_01_t1_q01",
                    "teil": 1,
                    "prompt_zh": "男士想要买什么？",
                    "question_de": "Was möchte der Mann kaufen?",
                    "options": [
                        {"key": "A", "text": "Einen Pullover"},
                        {"key": "B", "text": "Ein weißes Hemd"},
                        {"key": "C", "text": "Eine schwarze Hose"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Guten Tag, kann ich Ihnen helfen? - Ja, bitte. Ich suche ein weißes Hemd für eine Hochzeit. - Welche Größe haben Sie? - Größe 40, bitte.",
                    "transcript_de": "Guten Tag, kann ich Ihnen helfen? - Ja, bitte. Ich suche ein weißes Hemd für eine Hochzeit. - Welche Größe haben Sie? - Größe 40, bitte.",
                    "transcript_zh": "您好，有什么可以帮您的？- 是的。我在为一场婚礼找一件白衬衫。- 您的尺码是？- 40码，谢谢。",
                    "key_vocabulary": [
                        {"word": "das Hemd", "plural": "die Hemden", "meaning": "衬衫"},
                        {"word": "die Hochzeit", "plural": "die Hochzeiten", "meaning": "婚礼"}
                    ],
                    "explanation_zh": "男士明确回答：'Ich suche ein weißes Hemd'（我在找一件白衬衫），故选 B。"
                },
                {
                    "id": "a1_h_01_t1_q02",
                    "teil": 1,
                    "prompt_zh": "女士乘什么交通工具去火车站？",
                    "question_de": "Wie kommt die Frau zum Bahnhof?",
                    "options": [
                        {"key": "A", "text": "Mit dem Taxi"},
                        {"key": "B", "text": "Mit dem Bus"},
                        {"key": "C", "text": "Mit der U-Bahn"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Entschuldigung, fährt ein Bus zum Hauptbahnhof? - Nein, aber Sie können die U-Bahn Linie 2 nehmen. Die ist viel schneller. - Gut, danke schön!",
                    "transcript_de": "Entschuldigung, fährt ein Bus zum Hauptbahnhof? - Nein, aber Sie können die U-Bahn Linie 2 nehmen. Die ist viel schneller. - Gut, danke schön!",
                    "transcript_zh": "打扰一下，有去火车总站的公交车吗？- 没有，但您可以乘地铁2号线。那个快得多。- 好的，非常感谢！",
                    "key_vocabulary": [
                        {"word": "der Hauptbahnhof", "plural": "die Hauptbahnhöfe", "meaning": "火车总站"},
                        {"word": "die U-Bahn", "plural": "die U-Bahnen", "meaning": "地铁"}
                    ],
                    "explanation_zh": "对方告知没有公交车，建议乘地铁 'die U-Bahn Linie 2 nehmen'，女士表示同意，故选 C。"
                },
                {
                    "id": "a1_h_01_t1_q03",
                    "teil": 1,
                    "prompt_zh": "聚会什么时候开始？",
                    "question_de": "Wann beginnt die Party?",
                    "options": [
                        {"key": "A", "text": "Um 18:30 Uhr"},
                        {"key": "B", "text": "Um 19:00 Uhr"},
                        {"key": "C", "text": "Um 20:00 Uhr"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Hallo Julia! Kommst du heute Abend zu meiner Geburtstagsparty? - Gerne! Wann fängt sie an? - Um 20:00 Uhr geht es los.",
                    "transcript_de": "Hallo Julia! Kommst du heute Abend zu meiner Geburtstagsparty? - Gerne! Wann fängt sie an? - Um 20:00 Uhr geht es los.",
                    "transcript_zh": "你好茱莉亚！今晚来参加我的生日聚会吗？- 很乐意！什么时候开始？- 晚上8点（20:00）开始。",
                    "key_vocabulary": [
                        {"word": "die Geburtstagsparty", "plural": "die Geburtstagspartys", "meaning": "生日聚会"},
                        {"word": "losgehen", "meaning": "开始，出发"}
                    ],
                    "explanation_zh": "对话中明确说明 'Um 20:00 Uhr geht es los'（晚上8点开始），故选 C。"
                },
                {
                    "id": "a1_h_01_t1_q04",
                    "teil": 1,
                    "prompt_zh": "医生诊所周五什么时候开门？",
                    "question_de": "Wann ist die Praxis am Freitag geöffnet?",
                    "options": [
                        {"key": "A", "text": "Nur vormittags von 8 bis 12 Uhr"},
                        {"key": "B", "text": "Den ganzen Tag von 8 bis 18 Uhr"},
                        {"key": "C", "text": "Freitags geschlossen"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Praxis Dr. Weber, guten Tag. - Guten Tag, kann ich am Freitagnachmittag vorbeikommen? - Nein, freitags haben wir nur vormittags von 8 bis 12 Uhr geöffnet.",
                    "transcript_de": "Praxis Dr. Weber, guten Tag. - Guten Tag, kann ich am Freitagnachmittag vorbeikommen? - Nein, freitags haben wir nur vormittags von 8 bis 12 Uhr geöffnet.",
                    "transcript_zh": "韦伯医生诊所，您好。- 您好，我周五下午能过来吗？- 不行，周五我们只在上午8点到12点开门。",
                    "key_vocabulary": [
                        {"word": "die Praxis", "plural": "die Praxen", "meaning": "医生诊所"},
                        {"word": "geöffnet", "meaning": "开门的，营业的"}
                    ],
                    "explanation_zh": "前台明确说明：'freitags haben wir nur vormittags von 8 bis 12 Uhr geöffnet'，故选 A。"
                },
                {
                    "id": "a1_h_01_t1_q05",
                    "teil": 1,
                    "prompt_zh": "一杯咖啡多少钱？",
                    "question_de": "Wie viel kostet eine Tasse Kaffee?",
                    "options": [
                        {"key": "A", "text": "1,80 Euro"},
                        {"key": "B", "text": "2,40 Euro"},
                        {"key": "C", "text": "3,20 Euro"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Ich möchte bitte zahlen. Was kostet der Kaffee und das Stück Kuchen? - Der Kuchen kostet 3,20 Euro und der Kaffee 2,40 Euro. Zusammen macht das 5,60 Euro.",
                    "transcript_de": "Ich möchte bitte zahlen. Was kostet der Kaffee und das Stück Kuchen? - Der Kuchen kostet 3,20 Euro und der Kaffee 2,40 Euro. Zusammen macht das 5,60 Euro.",
                    "transcript_zh": "我想结账。咖啡和这块蛋糕多少钱？- 蛋糕3.20欧元，咖啡2.40欧元。一共5.60欧元。",
                    "key_vocabulary": [
                        {"word": "die Tasse", "plural": "die Tassen", "meaning": "杯子"},
                        {"word": "zahlen", "meaning": "付账"}
                    ],
                    "explanation_zh": "服务员说明 'der Kaffee 2,40 Euro'（咖啡2.40欧元），故选 B。"
                },
                {
                    "id": "a1_h_01_t1_q06",
                    "teil": 1,
                    "prompt_zh": "天气预报明天的天气如何？",
                    "question_de": "Wie wird das Wetter morgen?",
                    "options": [
                        {"key": "A", "text": "Es regnet den ganzen Tag"},
                        {"key": "B", "text": "Es schneit im Norden"},
                        {"key": "C", "text": "Sonnig und warm"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Und hier der Wetterbericht für morgen: Nach dem Regen heute wird es morgen überall sonnig und angenehm warm mit Temperaturen bis 24 Grad.",
                    "transcript_de": "Und hier der Wetterbericht für morgen: Nach dem Regen heute wird es morgen überall sonnig und angenehm warm mit Temperaturen bis 24 Grad.",
                    "transcript_zh": "接下来是明天的天气预报：在今天的降雨之后，明天各地将阳光明媚、温暖宜人，最高气温达24度。",
                    "key_vocabulary": [
                        {"word": "der Wetterbericht", "plural": "die Wetterberichte", "meaning": "天气预报"},
                        {"word": "sonnig", "meaning": "晴朗的，阳光明媚的"}
                    ],
                    "explanation_zh": "播报指出明天 'überall sonnig und angenehm warm'（到处晴朗且宜人暖和），故选 C。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_h_01_t2_q07",
                    "teil": 2,
                    "prompt_zh": "前往慕尼黑的 ICE 列车晚点 20 分钟。",
                    "question_de": "Der ICE nach München hat 20 Minuten Verspätung.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Achtung an Gleis 4: Der ICE 591 nach München Hauptbahnhof hat heute circa 20 Minuten Verspätung. Grund dafür ist eine Stellwerkstörung.",
                    "transcript_de": "Achtung an Gleis 4: Der ICE 591 nach München Hauptbahnhof hat heute circa 20 Minuten Verspätung. Grund dafür ist eine Stellwerkstörung.",
                    "transcript_zh": "请注意4站台广播：开往慕尼黑火车总站的ICE 591次列车今天晚点约20分钟。原因为信号所故障。",
                    "key_vocabulary": [
                        {"word": "das Gleis", "plural": "die Gleise", "meaning": "站台/轨道"},
                        {"word": "die Verspätung", "plural": "die Verspätungen", "meaning": "晚点，延误"}
                    ],
                    "explanation_zh": "广播明确说明 'hat heute circa 20 Minuten Verspätung'，陈述正确，选 R。"
                },
                {
                    "id": "a1_h_01_t2_q08",
                    "teil": 2,
                    "prompt_zh": "顾客现在可以在二楼购买打折运动鞋。",
                    "question_de": "Kunden können jetzt im 2. Stock reduzierte Sportschuhe kaufen.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "F",
                    "repeat_count": 1,
                    "audio_text_de": "Liebe Kunden, besuchen Sie unsere Sportabteilung im 3. Stock! Heute erhalten Sie 30 Prozent Rabatt auf alle Sportschuhe.",
                    "transcript_de": "Liebe Kunden, besuchen Sie unsere Sportabteilung im 3. Stock! Heute erhalten Sie 30 Prozent Rabatt auf alle Sportschuhe.",
                    "transcript_zh": "亲爱的顾客，欢迎光临我们三楼的运动部！今天所有运动鞋享受七折优惠（30%折扣）。",
                    "key_vocabulary": [
                        {"word": "der Stock", "meaning": "楼层 (im 3. Stock = 在3楼)"},
                        {"word": "der Rabatt", "plural": "die Rabatte", "meaning": "折扣"}
                    ],
                    "explanation_zh": "广播中说的是三楼（im 3. Stock），而非二楼，故陈述错误，选 F。"
                },
                {
                    "id": "a1_h_01_t2_q09",
                    "teil": 2,
                    "prompt_zh": "所有飞往法兰克福的乘客必须立刻前往 B12 登机口。",
                    "question_de": "Passagiere nach Frankfurt sollen sofort zum Flugsteig B12 gehen.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Letzter Aufruf für Flug LH 180 nach Frankfurt: Alle noch fehlenden Fluggäste begeben sich bitte unverzüglich zum Gate B12.",
                    "transcript_de": "Letzter Aufruf für Flug LH 180 nach Frankfurt: Alle noch fehlenden Fluggäste begeben sich bitte unverzüglich zum Gate B12.",
                    "transcript_zh": "飞往法兰克福的LH 180航班最后登机催促：请所有尚未登机的乘客立即前往B12登机口。",
                    "key_vocabulary": [
                        {"word": "der Flugsteig", "plural": "die Flugsteige", "meaning": "登机口 (Gate)"},
                        {"word": "unverzüglich", "meaning": "立即，刻不容缓"}
                    ],
                    "explanation_zh": "机场广播要求 'unverzüglich zum Gate B12'，陈述正确，选 R。"
                },
                {
                    "id": "a1_h_01_t2_q10",
                    "teil": 2,
                    "prompt_zh": "商场将在 15 分钟后停止营业。",
                    "question_de": "Das Kaufhaus schließt in 15 Minuten.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Verehrte Kunden, unser Kaufhaus schließt in 15 Minuten. Bitte gehen Sie nun zu den Kassen. Wir danken für Ihren Besuch.",
                    "transcript_de": "Verehrte Kunden, unser Kaufhaus schließt in 15 Minuten. Bitte gehen Sie nun zu den Kassen. Wir danken für Ihren Besuch.",
                    "transcript_zh": "尊敬的顾客，本商场将于15分钟后关门。请您现在前往收银台。感谢您的光临。",
                    "key_vocabulary": [
                        {"word": "schließen", "meaning": "关闭，关门"},
                        {"word": "die Kasse", "plural": "die Kassen", "meaning": "收银台"}
                    ],
                    "explanation_zh": "广播明确说明 'unser Kaufhaus schließt in 15 Minuten'，陈述正确，选 R。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_h_01_t3_q11",
                    "teil": 3,
                    "prompt_zh": "托马斯应该给谁回电话？",
                    "question_de": "Wen soll Thomas zurückrufen?",
                    "options": [
                        {"key": "A", "text": "Herrn Schneider"},
                        {"key": "B", "text": "Frau Meier"},
                        {"key": "C", "text": "Seine Mutter"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Hallo Thomas, hier ist Karin Meier von der Sprachschule. Bitte rufen Sie mich zurück wegen Ihres Deutschkurses. Meine Nummer ist 0172-884920.",
                    "transcript_de": "Hallo Thomas, hier ist Karin Meier von der Sprachschule. Bitte rufen Sie mich zurück wegen Ihres Deutschkurses. Meine Nummer ist 0172-884920.",
                    "transcript_zh": "你好托马斯，我是语言班的卡琳·迈尔（Karin Meier）。请您就德语课程的事给我回个电话。我的号码是0172-884920。",
                    "key_vocabulary": [
                        {"word": "zurückrufen", "meaning": "回电话 (可分动词)"},
                        {"word": "die Sprachschule", "plural": "die Sprachschulen", "meaning": "语言学校"}
                    ],
                    "explanation_zh": "留言人自我介绍为 'Karin Meier' 并要求 'Bitte rufen Sie mich zurück'，故选 B。"
                },
                {
                    "id": "a1_h_01_t3_q12",
                    "teil": 3,
                    "prompt_zh": "汽车什么时候可以修好取走？",
                    "question_de": "Wann kann das Auto abgeholt werden?",
                    "options": [
                        {"key": "A", "text": "Heute um 17 Uhr"},
                        {"key": "B", "text": "Morgen ab 14 Uhr"},
                        {"key": "C", "text": "Am Samstagvormittag"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Guten Tag Herr Bauer, Auto-Werkstatt Müller hier. Ihr Wagen ist morgen ab 14 Uhr fertig zur Abholung. Sie können bis 18 Uhr vorbeikommen.",
                    "transcript_de": "Guten Tag Herr Bauer, Auto-Werkstatt Müller hier. Ihr Wagen ist morgen ab 14 Uhr fertig zur Abholung. Sie können bis 18 Uhr vorbeikommen.",
                    "transcript_zh": "鲍尔先生您好，这里是米勒汽车维修厂。您的车辆明天下午14点起可供取走。您可以在18点之前过来。",
                    "key_vocabulary": [
                        {"word": "abholen", "meaning": "取，接 (可分动词)"},
                        {"word": "die Werkstatt", "plural": "die Werkstätten", "meaning": "车间，修理厂"}
                    ],
                    "explanation_zh": "修理厂通知 'morgen ab 14 Uhr fertig zur Abholung'，故选 B。"
                },
                {
                    "id": "a1_h_01_t3_q13",
                    "teil": 3,
                    "prompt_zh": "明天的德语课在哪个教室上？",
                    "question_de": "In welchem Raum findet der Deutschkurs morgen statt?",
                    "options": [
                        {"key": "A", "text": "Im Raum 104"},
                        {"key": "B", "text": "Im Raum 208"},
                        {"key": "C", "text": "Im Raum 310"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Hallo zusammen, hier ist eure Lehrerin Frau Becker. Achtung: Unser Deutschkurs morgen findet nicht in Raum 104 statt, sondern im Raum 208.",
                    "transcript_de": "Hallo zusammen, hier ist eure Lehrerin Frau Becker. Achtung: Unser Deutschkurs morgen findet nicht in Raum 104 statt, sondern im Raum 208.",
                    "transcript_zh": "大家好，我是你们的贝克尔老师。请注意：我们明天的德语课不在104教室，而是在208教室。",
                    "key_vocabulary": [
                        {"word": "der Raum", "plural": "die Räume", "meaning": "房间，教室"},
                        {"word": "stattfinden", "meaning": "举行，发生 (可分动词)"}
                    ],
                    "explanation_zh": "老师强调不在104，而是在208教室（'im Raum 208'），故选 B。"
                },
                {
                    "id": "a1_h_01_t3_q14",
                    "teil": 3,
                    "prompt_zh": "租房押金是多少钱？",
                    "question_de": "Wie hoch ist die Kaution für die Wohnung?",
                    "options": [
                        {"key": "A", "text": "500 Euro"},
                        {"key": "B", "text": "800 Euro"},
                        {"key": "C", "text": "1200 Euro"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Guten Tag, hier ist die Hausverwaltung. Die Miete für die Wohnung beträgt 600 Euro und die Kaution sind zwei Monatsmieten, also 1200 Euro.",
                    "transcript_de": "Guten Tag, hier ist die Hausverwaltung. Die Miete für die Wohnung beträgt 600 Euro und die Kaution sind zwei Monatsmieten, also 1200 Euro.",
                    "transcript_zh": "您好，这里是房屋管理处。该公寓租金为600欧元，押金为两个月租金，即1200欧元。",
                    "key_vocabulary": [
                        {"word": "die Kaution", "plural": "die Kautionen", "meaning": "押金"},
                        {"word": "die Miete", "plural": "die Mieten", "meaning": "房租"}
                    ],
                    "explanation_zh": "留言中明确计算：'also 1200 Euro'，故选 C。"
                },
                {
                    "id": "a1_h_01_t3_q15",
                    "teil": 3,
                    "prompt_zh": "图书馆周六几点关门？",
                    "question_de": "Wann schließt die Stadtbibliothek am Samstag?",
                    "options": [
                        {"key": "A", "text": "Um 14 Uhr"},
                        {"key": "B", "text": "Um 16 Uhr"},
                        {"key": "C", "text": "Um 18 Uhr"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Hier ist die automatische Auskunft der Stadtbibliothek. Unsere Öffnungszeiten am Samstag sind von 10:00 Uhr bis 14:00 Uhr.",
                    "transcript_de": "Hier ist die automatische Auskunft der Stadtbibliothek. Unsere Öffnungszeiten am Samstag sind von 10:00 Uhr bis 14:00 Uhr.",
                    "transcript_zh": "这里是市立图书馆自动语音问询。我们周六的开放时间为上午10:00至下午14:00。",
                    "key_vocabulary": [
                        {"word": "die Stadtbibliothek", "plural": "die Stadtbibliotheken", "meaning": "市立图书馆"},
                        {"word": "die Öffnungszeiten", "meaning": "开放/营业时间"}
                    ],
                    "explanation_zh": "自动问询说明周六开放至14:00（'bis 14:00 Uhr'），故选 A。"
                }
            ]
        }
    },

    # ── SET 02 ──────────────────────────────────────────────────────────────
    {
        "set_id": 2,
        "title_de": "Goethe-Zertifikat A1 Modellsatz 02",
        "title_zh": "歌德 A1 官方全真模考卷 02",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_h_02_t1_q01",
                    "teil": 1,
                    "prompt_zh": "女士喝什么？",
                    "question_de": "Was trinkt die Frau?",
                    "options": [
                        {"key": "A", "text": "Mineralwasser mit Zitrone"},
                        {"key": "B", "text": "Orangensaft"},
                        {"key": "C", "text": "Schwarzen Tee"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Möchten Sie etwas trinken? Wir haben Tee, Saft und Mineralwasser. - Ein Mineralwasser mit Zitrone bitte, danke.",
                    "transcript_de": "Möchten Sie etwas trinken? Wir haben Tee, Saft und Mineralwasser. - Ein Mineralwasser mit Zitrone bitte, danke.",
                    "transcript_zh": "您想喝点什么吗？我们有茶、果汁和矿泉水。- 请给我一杯加柠檬的矿泉水，谢谢。",
                    "key_vocabulary": [{"word": "das Mineralwasser", "meaning": "矿泉水"}],
                    "explanation_zh": "女士点单：'Ein Mineralwasser mit Zitrone bitte'，选 A。"
                },
                {
                    "id": "a1_h_02_t1_q02",
                    "teil": 1,
                    "prompt_zh": "男士什么时候有空去健身房？",
                    "question_de": "Wann hat der Mann Zeit für das Fitnessstudio?",
                    "options": [
                        {"key": "A", "text": "Am Dienstagabend"},
                        {"key": "B", "text": "Am Donnerstagabend"},
                        {"key": "C", "text": "Am Samstagmorgen"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Gehen wir am Dienstag ins Fitnessstudio? - Dienstag geht leider nicht. Aber am Donnerstagabend habe ich Zeit.",
                    "transcript_de": "Gehen wir am Dienstag ins Fitnessstudio? - Dienstag geht leider nicht. Aber am Donnerstagabend habe ich Zeit.",
                    "transcript_zh": "我们周二去健身房吗？- 周二恐怕不行。但周四晚上我有空。",
                    "key_vocabulary": [{"word": "das Fitnessstudio", "meaning": "健身房"}],
                    "explanation_zh": "男士确认 'am Donnerstagabend habe ich Zeit'，选 B。"
                },
                {
                    "id": "a1_h_02_t1_q03",
                    "teil": 1,
                    "prompt_zh": "火车站售票窗口在几号？",
                    "question_de": "Welcher Schalter ist geöffnet?",
                    "options": [
                        {"key": "A", "text": "Schalter 2"},
                        {"key": "B", "text": "Schalter 5"},
                        {"key": "C", "text": "Schalter 8"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Wo kann ich Fahrkarten kaufen? - Schalter 2 ist geschlossen, bitte gehen Sie zu Schalter 5.",
                    "transcript_de": "Wo kann ich Fahrkarten kaufen? - Schalter 2 ist geschlossen, bitte gehen Sie zu Schalter 5.",
                    "transcript_zh": "我在哪里可以买车票？- 2号窗口关闭了，请您去5号窗口。",
                    "key_vocabulary": [{"word": "der Schalter", "meaning": "售票窗口/服务台"}],
                    "explanation_zh": "明确指出请去5号窗口（'zu Schalter 5'），选 B。"
                },
                {
                    "id": "a1_h_02_t1_q04",
                    "teil": 1,
                    "prompt_zh": "这本书一共多少页？",
                    "question_de": "Wie viele Seiten hat das Buch?",
                    "options": [
                        {"key": "A", "text": "120 Seiten"},
                        {"key": "B", "text": "180 Seiten"},
                        {"key": "C", "text": "240 Seiten"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Ist der Roman sehr dick? - Nein, er ist ziemlich kurz, er hat nur 180 Seiten.",
                    "transcript_de": "Ist der Roman sehr dick? - Nein, er ist ziemlich kurz, er hat nur 180 Seiten.",
                    "transcript_zh": "这部小说很厚吗？- 不，挺短的，只有180页。",
                    "key_vocabulary": [{"word": "die Seite", "plural": "die Seiten", "meaning": "页，页面"}],
                    "explanation_zh": "明确说明 'er hat nur 180 Seiten'，选 B。"
                },
                {
                    "id": "a1_h_02_t1_q05",
                    "teil": 1,
                    "prompt_zh": "两个人打算在哪里见面？",
                    "question_de": "Wo treffen sich die beiden?",
                    "options": [
                        {"key": "A", "text": "Vor dem Kino"},
                        {"key": "B", "text": "Im Café am Markt"},
                        {"key": "C", "text": "Im Park"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Treffen wir uns im Café? - Nein, lass uns direkt vor dem Kino treffen, um Viertel vor acht.",
                    "transcript_de": "Treffen wir uns im Café? - Nein, lass uns direkt vor dem Kino treffen, um Viertel vor acht.",
                    "transcript_zh": "我们在咖啡馆见面吗？- 不，我们直接在电影院门口见吧，七点四十五分。",
                    "key_vocabulary": [{"word": "das Kino", "meaning": "电影院"}],
                    "explanation_zh": "对方建议 'direkt vor dem Kino treffen'，选 A。"
                },
                {
                    "id": "a1_h_02_t1_q06",
                    "teil": 1,
                    "prompt_zh": "谁生病了？",
                    "question_de": "Wer ist krank?",
                    "options": [
                        {"key": "A", "text": "Die Tochter"},
                        {"key": "B", "text": "Der Sohn"},
                        {"key": "C", "text": "Der Vater"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Kann Markus heute zur Schule kommen? - Markus ist gesund, aber meine Tochter Lena hat hohes Fieber und bleibt im Bett.",
                    "transcript_de": "Kann Markus heute zur Schule kommen? - Markus ist gesund, aber meine Tochter Lena hat hohes Fieber und bleibt im Bett.",
                    "transcript_zh": "马库斯今天能来学校吗？- 马库斯身体健康，但我女儿莉娜发高烧，留在床上休息。",
                    "key_vocabulary": [{"word": "das Fieber", "meaning": "发烧"}],
                    "explanation_zh": "母亲说明是女儿莉娜发烧（'meine Tochter Lena hat hohes Fieber'），选 A。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_h_02_t2_q07",
                    "teil": 2,
                    "prompt_zh": "12路公交车今天不停靠中心广场。",
                    "question_de": "Der Bus 12 hält heute nicht am Marktplatz.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Fahrgastinformation: Wegen einer Baustelle kann die Buslinie 12 die Haltestelle Marktplatz heute nicht anfahren.",
                    "transcript_de": "Fahrgastinformation: Wegen einer Baustelle kann die Buslinie 12 die Haltestelle Marktplatz heute nicht anfahren.",
                    "transcript_zh": "乘客须知：由于施工，12路公交车今天无法停靠集市广场站。",
                    "key_vocabulary": [{"word": "die Baustelle", "meaning": "施工现场"}],
                    "explanation_zh": "广播说明不停靠集市广场，陈述正确，选 R。"
                },
                {
                    "id": "a1_h_02_t2_q08",
                    "teil": 2,
                    "prompt_zh": "游泳池今天全天免费对儿童开放。",
                    "question_de": "Das Schwimmbad ist heute für Kinder kostenlos.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "F",
                    "repeat_count": 1,
                    "audio_text_de": "Achtung Badegäste: Kinder unter 6 Jahren zahlen heute nur den halben Preis von 2 Euro.",
                    "transcript_de": "Achtung Badegäste: Kinder unter 6 Jahren zahlen heute nur den halben Preis von 2 Euro.",
                    "transcript_zh": "游泳顾客请注意：6岁以下儿童今天享受半价2欧元。",
                    "key_vocabulary": [{"word": "kostenlos", "meaning": "免费的"}],
                    "explanation_zh": "广播说是半价2欧元（halber Preis），并非完全免费（kostenlos），故选 F。"
                },
                {
                    "id": "a1_h_02_t2_q09",
                    "teil": 2,
                    "prompt_zh": "火车上的餐车车厢在第 7 节车厢。",
                    "question_de": "Das Bordrestaurant befindet sich in Wagen 7.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Sehr geehrte Fahrgäste, unser Bordrestaurant im Wagen 7 hat ab sofort für Sie geöffnet. Wir freuen uns auf Sie.",
                    "transcript_de": "Sehr geehrte Fahrgäste, unser Bordrestaurant im Wagen 7 hat ab sofort für Sie geöffnet. Wir freuen uns auf Sie.",
                    "transcript_zh": "尊敬的旅客，我们位于7号车厢的餐车现已为您开放。期待您的光临。",
                    "key_vocabulary": [{"word": "das Bordrestaurant", "meaning": "列车餐车"}],
                    "explanation_zh": "明确说明 'im Wagen 7'，陈述正确，选 R。"
                },
                {
                    "id": "a1_h_02_t2_q10",
                    "teil": 2,
                    "prompt_zh": "机场地下停车场现在已满，无法停车。",
                    "question_de": "Die Tiefgarage am Flughafen ist voll besetzt.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Achtung Autofahrer: Das Parkhaus P1 und die Tiefgarage sind derzeit voll besetzt. Bitte nutzen Sie Parkplatz P4.",
                    "transcript_de": "Achtung Autofahrer: Das Parkhaus P1 und die Tiefgarage sind derzeit voll besetzt. Bitte nutzen Sie Parkplatz P4.",
                    "transcript_zh": "驾车者请注意：P1停车楼及地下车库目前已满。请使用P4停车场。",
                    "key_vocabulary": [{"word": "die Tiefgarage", "meaning": "地下车库"}],
                    "explanation_zh": "广播说明地下车库 voll besetzt（已满），陈述正确，选 R。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_h_02_t3_q11",
                    "teil": 3,
                    "prompt_zh": "会议推迟到星期几？",
                    "question_de": "Auf welchen Tag ist der Termin verschoben?",
                    "options": [
                        {"key": "A", "text": "Mittwoch"},
                        {"key": "B", "text": "Donnerstag"},
                        {"key": "C", "text": "Freitag"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Guten Tag Frau Vogel, hier ist Herr Klein. Unser Termin am Mittwoch fällt leider aus. Wir treffen uns stattdessen am Donnerstag um 10 Uhr.",
                    "transcript_de": "Guten Tag Frau Vogel, hier ist Herr Klein. Unser Termin am Mittwoch fällt leider aus. Wir treffen uns stattdessen am Donnerstag um 10 Uhr.",
                    "transcript_zh": "沃格尔女士您好，我是克莱恩。我们周三的约会取消了。改在周四上午10点见面。",
                    "key_vocabulary": [{"word": "verschieben", "meaning": "推迟，改期"}],
                    "explanation_zh": "留言说明改在周四（'am Donnerstag'），选 B。"
                },
                {
                    "id": "a1_h_02_t3_q12",
                    "teil": 3,
                    "prompt_zh": "包裹被放在哪里了？",
                    "question_de": "Wo liegt das Paket?",
                    "options": [
                        {"key": "A", "text": "Vor der Haustür"},
                        {"key": "B", "text": "Beim Nachbarn Herr Weber"},
                        {"key": "C", "text": "In der Postfiliale"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Hallo, hier ist der Paketdienst. Ich konnte Sie leider nicht antreffen. Ich habe Ihr Paket beim Nachbarn Herrn Weber im 1. Stock abgegeben.",
                    "transcript_de": "Hallo, hier ist der Paketdienst. Ich konnte Sie leider nicht antreffen. Ich habe Ihr Paket beim Nachbarn Herrn Weber im 1. Stock abgegeben.",
                    "transcript_zh": "您好，这里是快递服务。刚才没能碰上您。我把您的包裹交给了1楼的邻居韦伯先生。",
                    "key_vocabulary": [{"word": "das Paket", "meaning": "包裹"}, {"word": "der Nachbar", "meaning": "邻居"}],
                    "explanation_zh": "快递员交待在邻居处（'Beim Nachbarn Herrn Weber'），选 B。"
                },
                {
                    "id": "a1_h_02_t3_q13",
                    "teil": 3,
                    "prompt_zh": "请假条应该寄到哪个邮箱？",
                    "question_de": "Wohin soll die Krankmeldung geschickt werden?",
                    "options": [
                        {"key": "A", "text": "personal@firma.de"},
                        {"key": "B", "text": "chef@firma.de"},
                        {"key": "C", "text": "info@firma.de"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Guten Morgen Herr Schmidt, hier ist das Sekretariat. Bitte senden Sie das Attest vom Arzt per E-Mail an personal@firma.de.",
                    "transcript_de": "Guten Morgen Herr Schmidt, hier ist das Sekretariat. Bitte senden Sie das Attest vom Arzt per E-Mail an personal@firma.de.",
                    "transcript_zh": "施密特先生早上好，这里是秘书处。请将医生的病假证明通过电子邮件发送至 personal@firma.de。",
                    "key_vocabulary": [{"word": "das Attest", "meaning": "医生证明"}],
                    "explanation_zh": "明确指定邮箱 'personal@firma.de'，选 A。"
                },
                {
                    "id": "a1_h_02_t3_q14",
                    "teil": 3,
                    "prompt_zh": "租房中介的电话号码是多少？",
                    "question_de": "Wie lautet die Telefonnummer?",
                    "options": [
                        {"key": "A", "text": "030 - 45 67 89"},
                        {"key": "B", "text": "030 - 54 76 98"},
                        {"key": "C", "text": "030 - 45 76 89"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Hier ist Immobilien Schulz. Für Rückfragen erreichen Sie uns unter der Berliner Nummer 030 - 45 67 89.",
                    "transcript_de": "Hier ist Immobilien Schulz. Für Rückfragen erreichen Sie uns unter der Berliner Nummer 030 - 45 67 89.",
                    "transcript_zh": "这里是舒尔茨房产中介。如有疑问请拨打柏林号码 030 - 45 67 89。",
                    "key_vocabulary": [{"word": "die Nummer", "meaning": "号码"}],
                    "explanation_zh": "念出的数字为 45 67 89（fünfundvierzig, siebenundsechzig, neunundachtzig），选 A。"
                },
                {
                    "id": "a1_h_02_t3_q15",
                    "teil": 3,
                    "prompt_zh": "去机场应该坐几路公交车？",
                    "question_de": "Welchen Bus soll man zum Flughafen nehmen?",
                    "options": [
                        {"key": "A", "text": "Linie 100"},
                        {"key": "B", "text": "Linie 200"},
                        {"key": "C", "text": "Linie X9"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Automatische Fahrplanauskunft: Der Expressbus Linie X9 fährt alle 10 Minuten direkt zum Terminal 1 des Flughafens.",
                    "transcript_de": "Automatische Fahrplanauskunft: Der Expressbus Linie X9 fährt alle 10 Minuten direkt zum Terminal 1 des Flughafens.",
                    "transcript_zh": "自动时刻表问询：快速公交X9线每10分钟一班直达机场1号航站楼。",
                    "key_vocabulary": [{"word": "der Expressbus", "meaning": "快速公交车"}],
                    "explanation_zh": "直达机场的是 'Linie X9'，选 C。"
                }
            ]
        }
    },

    # ── SET 03 ──────────────────────────────────────────────────────────────
    {
        "set_id": 3,
        "title_de": "Goethe-Zertifikat A1 Modellsatz 03",
        "title_zh": "歌德 A1 官方全真模考卷 03",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_h_03_t1_q01",
                    "teil": 1,
                    "prompt_zh": "女士住在哪个房间？",
                    "question_de": "In welchem Zimmer wohnt die Frau?",
                    "options": [
                        {"key": "A", "text": "Zimmer 214"},
                        {"key": "B", "text": "Zimmer 314"},
                        {"key": "C", "text": "Zimmer 414"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Hier ist Ihr Zimmerschlüssel. Sie haben Zimmer 314 im dritten Stock. Der Aufzug ist gleich rechts. - Vielen Dank!",
                    "transcript_de": "Hier ist Ihr Zimmerschlüssel. Sie haben Zimmer 314 im dritten Stock. Der Aufzug ist gleich rechts. - Vielen Dank!",
                    "transcript_zh": "这是您的房间钥匙。您的房间是三楼的314房间。电梯就在右侧。- 非常感谢！",
                    "key_vocabulary": [{"word": "der Zimmerschlüssel", "meaning": "房间钥匙"}],
                    "explanation_zh": "前台明确交待 'Zimmer 314'，选 B。"
                },
                {
                    "id": "a1_h_03_t1_q02",
                    "teil": 1,
                    "prompt_zh": "男士想吃什么？",
                    "question_de": "Was möchte der Mann essen?",
                    "options": [
                        {"key": "A", "text": "Eine Bratwurst mit Pommes"},
                        {"key": "B", "text": "Einen gemischten Salat"},
                        {"key": "C", "text": "Eine Gemüsesuppe"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Haben Sie schon gewählt? - Ja, für mich bitte eine Bratwurst mit Pommes frites und Ketchup.",
                    "transcript_de": "Haben Sie schon gewählt? - Ja, für mich bitte eine Bratwurst mit Pommes frites und Ketchup.",
                    "transcript_zh": "您选好了吗？- 是的，请给我一份烤肠配炸薯条和番茄酱。",
                    "key_vocabulary": [{"word": "die Bratwurst", "meaning": "煎烤香肠"}],
                    "explanation_zh": "男士点餐：'eine Bratwurst mit Pommes frites'，选 A。"
                },
                {
                    "id": "a1_h_03_t1_q03",
                    "teil": 1,
                    "prompt_zh": "女士什么时候去德国？",
                    "question_de": "Wann reist die Frau nach Deutschland?",
                    "options": [
                        {"key": "A", "text": "Im Juli"},
                        {"key": "B", "text": "Im August"},
                        {"key": "C", "text": "Im September"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Fährst du im Sommer nach Berlin? - Nicht im Juli oder August, es ist zu heiß. Ich fahre Anfang September.",
                    "transcript_de": "Fährst du im Sommer nach Berlin? - Nicht im Juli oder August, es ist zu heiß. Ich fahre Anfang September.",
                    "transcript_zh": "你夏天去柏林吗？- 七月或八月不去，太热了。我九月初去。",
                    "key_vocabulary": [{"word": "reisen", "meaning": "旅行，前往"}],
                    "explanation_zh": "女士说明 'Ich fahre Anfang September'，选 C。"
                },
                {
                    "id": "a1_h_03_t1_q04",
                    "teil": 1,
                    "prompt_zh": "这件夹克打折后多少钱？",
                    "question_de": "Wie viel kostet die Jacke im Angebot?",
                    "options": [
                        {"key": "A", "text": "49 Euro"},
                        {"key": "B", "text": "69 Euro"},
                        {"key": "C", "text": "89 Euro"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Die Jacke kostete früher 89 Euro, aber heute im Sonderangebot nur 49 Euro.",
                    "transcript_de": "Die Jacke kostete früher 89 Euro, aber heute im Sonderangebot nur 49 Euro.",
                    "transcript_zh": "这件夹克之前卖89欧元，但今天特价只要49欧元。",
                    "key_vocabulary": [{"word": "das Sonderangebot", "meaning": "特价特惠"}],
                    "explanation_zh": "特价价格为 'nur 49 Euro'，选 A。"
                },
                {
                    "id": "a1_h_03_t1_q05",
                    "teil": 1,
                    "prompt_zh": "现在几点钟？",
                    "question_de": "Wie spät ist es jetzt?",
                    "options": [
                        {"key": "A", "text": "14:15 Uhr (Viertel nach zwei)"},
                        {"key": "B", "text": "14:30 Uhr (Halb drei)"},
                        {"key": "C", "text": "14:45 Uhr (Viertel vor drei)"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Entschuldigung, wie spät ist es? - Einen Moment... Es ist genau halb drei.",
                    "transcript_de": "Entschuldigung, wie spät ist es? - Einen Moment... Es ist genau halb drei.",
                    "transcript_zh": "打扰一下，现在几点了？- 稍等……正好两点半（14:30）。",
                    "key_vocabulary": [{"word": "halb drei", "meaning": "两点半 (14:30)"}],
                    "explanation_zh": "回答是 'halb drei'（两点半 = 14:30），选 B。"
                },
                {
                    "id": "a1_h_03_t1_q06",
                    "teil": 1,
                    "prompt_zh": "男士的爱好是什么？",
                    "question_de": "Was ist das Hobby des Mannes?",
                    "options": [
                        {"key": "A", "text": "Fußball spielen"},
                        {"key": "B", "text": "Gitarre spielen"},
                        {"key": "C", "text": "Bücher lesen"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Was machst du gern in deiner Freizeit? Spielst du Fußball? - Nein, Sport mag ich nicht so gern. Ich spiele Gitarre in einer Band.",
                    "transcript_de": "Was machst du gern in deiner Freizeit? Spielst du Fußball? - Nein, Sport mag ich nicht so gern. Ich spiele Gitarre in einer Band.",
                    "transcript_zh": "你空闲时间喜欢做什么？踢足球吗？- 不，我不太喜欢体育。我在一个乐队里弹吉他。",
                    "key_vocabulary": [{"word": "die Gitarre", "meaning": "吉他"}],
                    "explanation_zh": "男士说明 'Ich spiele Gitarre in einer Band'，选 B。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_h_03_t2_q07",
                    "teil": 2,
                    "prompt_zh": "在 3 号候机区有免费咖啡供应。",
                    "question_de": "Im Wartebereich 3 gibt es kostenlosen Kaffee.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "F",
                    "repeat_count": 1,
                    "audio_text_de": "Achtung an alle Fluggäste: Wegen der Flugverspätung erhalten Sie im Wartebereich 3 kostenlose Erfrischungsgetränke und Wasser.",
                    "transcript_de": "Achtung an alle Fluggäste: Wegen der Flugverspätung erhalten Sie im Wartebereich 3 kostenlose Erfrischungsgetränke und Wasser.",
                    "transcript_zh": "各位旅客请注意：由于航班延误，您可在3号候机区领取免费清凉饮料和水。",
                    "key_vocabulary": [{"word": "das Erfrischungsgetränk", "meaning": "清凉软饮"}],
                    "explanation_zh": "广播提到提供的是清凉饮料和水（Erfrischungsgetränke und Wasser），并非咖啡，故选 F。"
                },
                {
                    "id": "a1_h_03_t2_q08",
                    "teil": 2,
                    "prompt_zh": "游泳馆今天因水温维护关闭。",
                    "question_de": "Das Hallenbad bleibt heute wegen Wartungsarbeiten geschlossen.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Liebe Besucher, unser Hallenbad bleibt heute ganztägig wegen dringender Wartungsarbeiten geschlossen. Morgen öffnen wir wieder ab 8 Uhr.",
                    "transcript_de": "Liebe Besucher, unser Hallenbad bleibt heute ganztägig wegen dringender Wartungsarbeiten geschlossen. Morgen öffnen wir wieder ab 8 Uhr.",
                    "transcript_zh": "亲爱的访客，因紧急维护工作，我们的室内游泳馆今天全天关闭。明天上午8点恢复开放。",
                    "key_vocabulary": [{"word": "die Wartungsarbeiten", "meaning": "维护保养工作"}],
                    "explanation_zh": "广播确认 'bleibt heute ... geschlossen'，陈述正确，选 R。"
                },
                {
                    "id": "a1_h_03_t2_q09",
                    "teil": 2,
                    "prompt_zh": "去汉堡的火车改在 8 站台发车。",
                    "question_de": "Der Zug nach Hamburg fährt heute von Gleis 8 ab.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Gleisänderung: Der Regional-Express nach Hamburg fährt heute abweichend von Gleis 8 statt Gleis 3.",
                    "transcript_de": "Gleisänderung: Der Regional-Express nach Hamburg fährt heute abweichend von Gleis 8 statt Gleis 3.",
                    "transcript_zh": "站台变更通知：开往汉堡的区域快车今天改由8站台发车，而非3站台。",
                    "key_vocabulary": [{"word": "die Gleisänderung", "meaning": "站台变更"}],
                    "explanation_zh": "明确改为8站台（von Gleis 8），陈述正确，选 R。"
                },
                {
                    "id": "a1_h_03_t2_q10",
                    "teil": 2,
                    "prompt_zh": "超市今天的草莓每盒只需 1 欧元。",
                    "question_de": "Die Erdbeeren kosten heute 1 Euro pro Schale.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "F",
                    "repeat_count": 1,
                    "audio_text_de": "Tagesangebot im Supermarkt: Frische deutsche Erdbeeren heute nur 1,99 Euro pro 500 Gramm Schale.",
                    "transcript_de": "Tagesangebot im Supermarkt: Frische deutsche Erdbeeren heute nur 1,99 Euro pro 500 Gramm Schale.",
                    "transcript_zh": "超市今日特惠：新鲜德国草莓今天每500克盒装仅售1.99欧元。",
                    "key_vocabulary": [{"word": "die Erdbeere", "plural": "die Erdbeeren", "meaning": "草莓"}],
                    "explanation_zh": "价格为 1.99 欧元而非 1 欧元，陈述错误，选 F。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_h_03_t3_q11",
                    "teil": 3,
                    "prompt_zh": "牙医预约改到了什么时间？",
                    "question_de": "Wann ist der neue Zahnarzttermin?",
                    "options": [
                        {"key": "A", "text": "Am Montag um 9 Uhr"},
                        {"key": "B", "text": "Am Dienstag um 15 Uhr"},
                        {"key": "C", "text": "Am Mittwoch um 11 Uhr"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Zahnarztpraxis Dr. Hoffmann hier. Frau Meier, Ihr Termin am Montag muss leider verschoben werden. Wir haben für Sie Dienstag um 15:00 Uhr reserviert.",
                    "transcript_de": "Zahnarztpraxis Dr. Hoffmann hier. Frau Meier, Ihr Termin am Montag muss leider verschoben werden. Wir haben für Sie Dienstag um 15:00 Uhr reserviert.",
                    "transcript_zh": "这里是霍夫曼牙医诊所。迈尔女士，您周一的预约必须改期。我们为您预留了周二下午15:00的时间。",
                    "key_vocabulary": [{"word": "der Zahnarzt", "meaning": "牙医"}],
                    "explanation_zh": "新预约时间为周二15点（'Dienstag um 15:00 Uhr'），选 B。"
                },
                {
                    "id": "a1_h_03_t3_q12",
                    "teil": 3,
                    "prompt_zh": "去歌剧院应该在哪一站下车？",
                    "question_de": "An welcher Haltestelle soll man für die Oper aussteigen?",
                    "options": [
                        {"key": "A", "text": "Rathaus"},
                        {"key": "B", "text": "Opernplatz"},
                        {"key": "C", "text": "Stadtpark"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Nächste Haltestelle: Opernplatz. Übergang zu den Linien U1 und U3. Ausstieg in Fahrtrichtung rechts zur Staatsoper.",
                    "transcript_de": "Nächste Haltestelle: Opernplatz. Übergang zu den Linien U1 und U3. Ausstieg in Fahrtrichtung rechts zur Staatsoper.",
                    "transcript_zh": "下一站：歌剧院广场（Opernplatz）。可换乘地铁U1和U3线。右侧车门开启前往国家歌剧院。",
                    "key_vocabulary": [{"word": "aussteigen", "meaning": "下车 (可分动词)"}],
                    "explanation_zh": "报站明确为 'Opernplatz'，选 B。"
                },
                {
                    "id": "a1_h_03_t3_q13",
                    "teil": 3,
                    "prompt_zh": "租车每天的费用是多少？",
                    "question_de": "Wie viel kostet der Mietwagen pro Tag?",
                    "options": [
                        {"key": "A", "text": "35 Euro"},
                        {"key": "B", "text": "55 Euro"},
                        {"key": "C", "text": "75 Euro"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Autovermietung Star: Unser Kompaktwagen kostet im Wochenend-Tarif nur 35 Euro pro Tag inklusive Vollkasko.",
                    "transcript_de": "Autovermietung Star: Unser Kompaktwagen kostet im Wochenend-Tarif nur 35 Euro pro Tag inklusive Vollkasko.",
                    "transcript_zh": "星辰租车：我们紧凑型轿车在周末特惠价下仅需每天35欧元（含全险）。",
                    "key_vocabulary": [{"word": "der Mietwagen", "meaning": "租赁汽车"}],
                    "explanation_zh": "价格为每天35欧元（'35 Euro pro Tag'），选 A。"
                },
                {
                    "id": "a1_h_03_t3_q14",
                    "teil": 3,
                    "prompt_zh": "需要给朋友带什么去野餐？",
                    "question_de": "Was soll man zum Picknick mitbringen?",
                    "options": [
                        {"key": "A", "text": "Brot und Käse"},
                        {"key": "B", "text": "Getränke und Pappteller"},
                        {"key": "C", "text": "Einen Kartoffelsalat"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Hi Paul! Ich bringe Brot und Würstchen mit. Kannst du bitte deinen leckeren Kartoffelsalat für unser Picknick machen?",
                    "transcript_de": "Hi Paul! Ich bringe Brot und Würstchen mit. Kannst du bitte deinen leckeren Kartoffelsalat für unser Picknick machen?",
                    "transcript_zh": "嗨保罗！我带面包和香肠。你能为我们的野餐做一份你拿手的土豆沙拉吗？",
                    "key_vocabulary": [{"word": "der Kartoffelsalat", "meaning": "土豆沙拉"}],
                    "explanation_zh": "朋友明确请求 'deinen leckeren Kartoffelsalat'，选 C。"
                },
                {
                    "id": "a1_h_03_t3_q15",
                    "teil": 3,
                    "prompt_zh": "护照可以在什么时间段领取？",
                    "question_de": "Wann kann der Reisepass abgeholt werden?",
                    "options": [
                        {"key": "A", "text": "Mo-Fr 8-12 Uhr"},
                        {"key": "B", "text": "Mo-Do 13-16 Uhr"},
                        {"key": "C", "text": "Nur am Samstag"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Bürgeramt Mitte: Ihr Reisepass liegt abholbereit vor. Öffnungszeiten der Passstelle sind Montag bis Freitag von 8 bis 12 Uhr.",
                    "transcript_de": "Bürgeramt Mitte: Ihr Reisepass liegt abholbereit vor. Öffnungszeiten der Passstelle sind Montag bis Freitag von 8 bis 12 Uhr.",
                    "transcript_zh": "米特区市民政务中心：您的护照已制好可供领取。护照办理处开放时间为周一至周五8点至12点。",
                    "key_vocabulary": [{"word": "der Reisepass", "meaning": "护照"}],
                    "explanation_zh": "开放时间为 'Montag bis Freitag von 8 bis 12 Uhr'，选 A。"
                }
            ]
        }
    },

    # ── SET 04 ──────────────────────────────────────────────────────────────
    {
        "set_id": 4,
        "title_de": "Goethe-Zertifikat A1 Modellsatz 04",
        "title_zh": "歌德 A1 官方全真模考卷 04",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_h_04_t1_q01",
                    "teil": 1,
                    "prompt_zh": "男士来自哪个国家？",
                    "question_de": "Woher kommt der Mann?",
                    "options": [
                        {"key": "A", "text": "Aus Österreich"},
                        {"key": "B", "text": "Aus der Schweiz"},
                        {"key": "C", "text": "Aus Polen"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Kommen Sie aus Deutschland? - Nein, ich komme aus der Schweiz, aus Zürich. Aber ich wohne jetzt in Frankfurt.",
                    "transcript_de": "Kommen Sie aus Deutschland? - Nein, ich komme aus der Schweiz, aus Zürich. Aber ich wohne jetzt in Frankfurt.",
                    "transcript_zh": "您来自德国吗？- 不，我来自瑞士苏黎世。但我现在住在法兰克福。",
                    "key_vocabulary": [{"word": "die Schweiz", "meaning": "瑞士 (阳性/阴性国名带冠词)"}],
                    "explanation_zh": "男士回答 'aus der Schweiz'（来自瑞士），选 B。"
                },
                {
                    "id": "a1_h_04_t1_q02",
                    "teil": 1,
                    "prompt_zh": "女士买了几张电影票？",
                    "question_de": "Wie viele Kinokarten kauft die Frau?",
                    "options": [
                        {"key": "A", "text": "Zwei Karten"},
                        {"key": "B", "text": "Drei Karten"},
                        {"key": "C", "text": "Vier Karten"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Guten Abend. Drei Karten für den Film um 20 Uhr bitte, für zwei Erwachsene und ein Kind.",
                    "transcript_de": "Guten Abend. Drei Karten für den Film um 20 Uhr bitte, für zwei Erwachsene und ein Kind.",
                    "transcript_zh": "晚上好。请给我三张晚上8点的电影票，两位成人和一位儿童。",
                    "key_vocabulary": [{"word": "die Karte", "plural": "die Karten", "meaning": "票，卡片"}],
                    "explanation_zh": "明确要求 'Drei Karten'（三张票），选 B。"
                },
                {
                    "id": "a1_h_04_t1_q03",
                    "teil": 1,
                    "prompt_zh": "去邮局应该怎么走？",
                    "question_de": "Wie kommt man zur Post?",
                    "options": [
                        {"key": "A", "text": "Geradeaus und dann rechts"},
                        {"key": "B", "text": "Die erste Straße links"},
                        {"key": "C", "text": "Über die Brücke"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Entschuldigung, wo ist die Post? - Gehen Sie hier immer geradeaus und an der Ampel biegen Sie nach rechts ab.",
                    "transcript_de": "Entschuldigung, wo ist die Post? - Gehen Sie hier immer geradeaus und an der Ampel biegen Sie nach rechts ab.",
                    "transcript_zh": "打扰一下，请问邮局在哪里？- 您一直往前直走，然后在红绿灯处右转。",
                    "key_vocabulary": [{"word": "geradeaus", "meaning": "直行"}, {"word": "rechts", "meaning": "右侧/向右"}],
                    "explanation_zh": "指路为 'immer geradeaus und ... nach rechts'，选 A。"
                },
                {
                    "id": "a1_h_04_t1_q04",
                    "teil": 1,
                    "prompt_zh": "男士买苹果花了多少钱？",
                    "question_de": "Wie viel bezahlt der Mann für die Äpfel?",
                    "options": [
                        {"key": "A", "text": "2,50 Euro"},
                        {"key": "B", "text": "3,00 Euro"},
                        {"key": "C", "text": "4,50 Euro"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Ein Kilo Äpfel bitte. - Das macht 2,50 Euro. Möchten Sie noch etwas? - Nein, das ist alles.",
                    "transcript_de": "Ein Kilo Äpfel bitte. - Das macht 2,50 Euro. Möchten Sie noch etwas? - Nein, das ist alles.",
                    "transcript_zh": "请给我一公斤苹果。- 一共2.50欧元。您还需要别的吗？- 不了，就这些。",
                    "key_vocabulary": [{"word": "der Apfel", "plural": "die Äpfel", "meaning": "苹果"}],
                    "explanation_zh": "摊主说明 'Das macht 2,50 Euro'，选 A。"
                },
                {
                    "id": "a1_h_04_t1_q05",
                    "teil": 1,
                    "prompt_zh": "火车将在几站台到达？",
                    "question_de": "Auf welchem Gleis kommt der Zug an?",
                    "options": [
                        {"key": "A", "text": "Gleis 1"},
                        {"key": "B", "text": "Gleis 6"},
                        {"key": "C", "text": "Gleis 11"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Einfahrt des ICE 78 aus Köln auf Gleis 11. Bitte treten Sie von der Bahnsteigkante zurück.",
                    "transcript_de": "Einfahrt des ICE 78 aus Köln auf Gleis 11. Bitte treten Sie von der Bahnsteigkante zurück.",
                    "transcript_zh": "来自科隆的ICE 78次列车进11站台。请站台上的旅客退至安全线以内。",
                    "key_vocabulary": [{"word": "die Einfahrt", "meaning": "进站"}],
                    "explanation_zh": "广播指明 'auf Gleis 11'，选 C。"
                },
                {
                    "id": "a1_h_04_t1_q06",
                    "teil": 1,
                    "prompt_zh": "女士最喜欢哪个季节？",
                    "question_de": "Welche Jahreszeit mag die Frau am liebsten?",
                    "options": [
                        {"key": "A", "text": "Den Frühling"},
                        {"key": "B", "text": "Den Sommer"},
                        {"key": "C", "text": "Den Herbst"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Magst du den Sommer auch so gern? - Nein, mir ist es oft zu heiß. Mein Lieblingsmonat ist der Mai, ich liebe den Frühling.",
                    "transcript_de": "Magst du den Sommer auch so gern? - Nein, mir ist es oft zu heiß. Mein Lieblingsmonat ist der Mai, ich liebe den Frühling.",
                    "transcript_zh": "你也那么喜欢夏天吗？- 不，我觉得夏天往往太热了。我最喜欢的月份是五月，我爱春天。",
                    "key_vocabulary": [{"word": "der Frühling", "meaning": "春天"}],
                    "explanation_zh": "女士明确表示 'ich liebe den Frühling'，选 A。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_h_04_t2_q07",
                    "teil": 2,
                    "prompt_zh": "火车站书店今天提前到 18 点关门。",
                    "question_de": "Die Bahnhofsbuchhandlung schließt heute um 18 Uhr.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "F",
                    "repeat_count": 1,
                    "audio_text_de": "Kundeninformation: Unsere Bahnhofsbuchhandlung im Hauptgebäude hat für Sie heute wie gewohnt bis 22 Uhr geöffnet.",
                    "transcript_de": "Kundeninformation: Unsere Bahnhofsbuchhandlung im Hauptgebäude hat für Sie heute wie gewohnt bis 22 Uhr geöffnet.",
                    "transcript_zh": "顾客须知：位于主楼的火车站书店今天照常为您营业至晚上22点。",
                    "key_vocabulary": [{"word": "die Buchhandlung", "meaning": "书店"}],
                    "explanation_zh": "广播说明营业至22点（'bis 22 Uhr'），而非18点，故选 F。"
                },
                {
                    "id": "a1_h_04_t2_q08",
                    "teil": 2,
                    "prompt_zh": "商场现在正在寻找一位走失的小女孩。",
                    "question_de": "Im Einkaufszentrum wird ein kleines Mädchen gesucht.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Wichtige Durchsage: Die kleine fünfjährige Sarah sucht ihre Mutter. Sarah wartet an der Information im Erdgeschoss.",
                    "transcript_de": "Wichtige Durchsage: Die kleine fünfjährige Sarah sucht ihre Mutter. Sarah wartet an der Information im Erdgeschoss.",
                    "transcript_zh": "重要广播：5岁的小女孩萨拉正在寻找她的妈妈。萨拉目前在一楼服务台等候。",
                    "key_vocabulary": [{"word": "das Erdgeschoss", "meaning": "一楼/底层"}],
                    "explanation_zh": "广播为寻找小女孩家长，陈述正确，选 R。"
                },
                {
                    "id": "a1_h_04_t2_q09",
                    "teil": 2,
                    "prompt_zh": "因大雪天气，所有城市公交车暂停运营。",
                    "question_de": "Wegen Schnee fahren heute keine Stadtbusse.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "F",
                    "repeat_count": 1,
                    "audio_text_de": "Verkehrsmeldung: Wegen Schneefalls kommt es auf allen Buslinien zu leichten Verspätungen. Alle Linien sind jedoch in Betrieb.",
                    "transcript_de": "Verkehrsmeldung: Wegen Schneefalls kommt es auf allen Buslinien zu leichten Verspätungen. Alle Linien sind jedoch in Betrieb.",
                    "transcript_zh": "交通简报：因降雪，所有公交线路均出现轻微晚点。但所有线路均在正常运营中。",
                    "key_vocabulary": [{"word": "der Schneefall", "meaning": "降雪"}],
                    "explanation_zh": "广播明确说明线路正常运行（'in Betrieb'），仅有轻微晚点，并未停运，故选 F。"
                },
                {
                    "id": "a1_h_04_t2_q10",
                    "teil": 2,
                    "prompt_zh": "4 号航站楼的旅客需要重新进行安检。",
                    "question_de": "Passagiere im Terminal 4 müssen nochmals durch die Sicherheitskontrolle.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Sicherheitsdurchsage: Alle Passagiere im Bereich Terminal 4 werden gebeten, sich erneut zur Sicherheitskontrolle zu begeben.",
                    "transcript_de": "Sicherheitsdurchsage: Alle Passagiere im Bereich Terminal 4 werden gebeten, sich erneut zur Sicherheitskontrolle zu begeben.",
                    "transcript_zh": "安保广播：请4号航站楼区域的所有旅客重新前往安全检查处。",
                    "key_vocabulary": [{"word": "die Sicherheitskontrolle", "meaning": "安全检查"}],
                    "explanation_zh": "广播要求重新安检（'erneut zur Sicherheitskontrolle'），陈述正确，选 R。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_h_04_t3_q11",
                    "teil": 3,
                    "prompt_zh": "朋友邀请参加什么活动？",
                    "question_de": "Zu welcher Veranstaltung lädt der Freund ein?",
                    "options": [
                        {"key": "A", "text": "Zum Geburtstag"},
                        {"key": "B", "text": "Zu einem Konzert"},
                        {"key": "C", "text": "Zum Fußballspiel"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Hallo Tim, ich habe zwei Freikarten für das Rockkonzert am Samstagabend. Hast du Lust mitzukommen? Meld dich mal!",
                    "transcript_de": "Hallo Tim, ich habe zwei Freikarten für das Rockkonzert am Samstagabend. Hast du Lust mitzukommen? Meld dich mal!",
                    "transcript_zh": "嗨蒂姆，我有两张周六晚摇滚音乐会的免费赠票。你想一起去吗？给我回个信！",
                    "key_vocabulary": [{"word": "das Konzert", "plural": "die Konzerte", "meaning": "音乐会"}],
                    "explanation_zh": "朋友明确说明是 'für das Rockkonzert'，选 B。"
                },
                {
                    "id": "a1_h_04_t3_q12",
                    "teil": 3,
                    "prompt_zh": "语言班的考试在什么时候进行？",
                    "question_de": "Wann findet die Prüfung im Sprachkurs statt?",
                    "options": [
                        {"key": "A", "text": "Am 12. Mai"},
                        {"key": "B", "text": "Am 18. Mai"},
                        {"key": "C", "text": "Am 24. Mai"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Wichtige Information der Volkshochschule: Die Abschlussprüfung für den A1-Kurs findet am Donnerstag, den 18. Mai ab 9 Uhr statt.",
                    "transcript_de": "Wichtige Information der Volkshochschule: Die Abschlussprüfung für den A1-Kurs findet am Donnerstag, den 18. Mai ab 9 Uhr statt.",
                    "transcript_zh": "业余大学重要通知：A1课程结业考试将于5月18日周四上午9点开始举行。",
                    "key_vocabulary": [{"word": "die Abschlussprüfung", "meaning": "结业考试"}],
                    "explanation_zh": "日期为 5月18日（'den 18. Mai'），选 B。"
                },
                {
                    "id": "a1_h_04_t3_q13",
                    "teil": 3,
                    "prompt_zh": "去柏林的机票价格是多少？",
                    "question_de": "Wie viel kostet der Flug nach Berlin?",
                    "options": [
                        {"key": "A", "text": "69 Euro"},
                        {"key": "B", "text": "99 Euro"},
                        {"key": "C", "text": "129 Euro"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Reisebüro Flugwelt: Unser Frühbucherangebot nach Berlin gibt es ab sofort für nur 69 Euro für Hin- und Rückflug.",
                    "transcript_de": "Reisebüro Flugwelt: Unser Frühbucherangebot nach Berlin gibt es ab sofort für nur 69 Euro für Hin- und Rückflug.",
                    "transcript_zh": "飞跃世界旅行社：飞往柏林的早鸟特惠即刻起仅需69欧元（包含往返机票）。",
                    "key_vocabulary": [{"word": "der Flug", "plural": "die Flüge", "meaning": "航班/飞行"}],
                    "explanation_zh": "特惠票价为 'nur 69 Euro'，选 A。"
                },
                {
                    "id": "a1_h_04_t3_q14",
                    "teil": 3,
                    "prompt_zh": "博物馆周一几点闭馆？",
                    "question_de": "Wann schließt das Museum am Montag?",
                    "options": [
                        {"key": "A", "text": "Um 17 Uhr"},
                        {"key": "B", "text": "Um 20 Uhr"},
                        {"key": "C", "text": "Montags ist geschlossen"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Kunstmuseum Info: Bitte beachten Sie, dass das Museum montags generell geschlossen bleibt. Di bis So 10 bis 18 Uhr.",
                    "transcript_de": "Kunstmuseum Info: Bitte beachten Sie, dass das Museum montags generell geschlossen bleibt. Di bis So 10 bis 18 Uhr.",
                    "transcript_zh": "艺术博物馆问询：请注意，本博物馆每周一例行闭馆。周二至周日10点至18点开放。",
                    "key_vocabulary": [{"word": "generell", "meaning": "通常，大体上"}],
                    "explanation_zh": "周一闭馆（'montags generell geschlossen'），选 C。"
                },
                {
                    "id": "a1_h_04_t3_q15",
                    "teil": 3,
                    "prompt_zh": "酒店早餐供应到几点？",
                    "question_de": "Bis wann gibt es im Hotel Frühstück?",
                    "options": [
                        {"key": "A", "text": "Bis 9:30 Uhr"},
                        {"key": "B", "text": "Bis 10:30 Uhr"},
                        {"key": "C", "text": "Bis 11:30 Uhr"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Hotel Stadtblick Rezeption: Unser reichhaltiges Frühstücksbuffet steht Ihnen täglich von 6:30 Uhr bis 10:30 Uhr im Restaurant zur Verfügung.",
                    "transcript_de": "Hotel Stadtblick Rezeption: Unser reichhaltiges Frühstücksbuffet steht Ihnen täglich von 6:30 Uhr bis 10:30 Uhr im Restaurant zur Verfügung.",
                    "transcript_zh": "城景酒店前台：我们丰富的自助早餐每天6:30至10:30在餐厅供应。",
                    "key_vocabulary": [{"word": "das Frühstück", "meaning": "早餐"}],
                    "explanation_zh": "早餐至 10:30 截止（'bis 10:30 Uhr'），选 B。"
                }
            ]
        }
    },

    # ── SET 05 ──────────────────────────────────────────────────────────────
    {
        "set_id": 5,
        "title_de": "Goethe-Zertifikat A1 Modellsatz 05",
        "title_zh": "歌德 A1 官方全真模考卷 05",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_h_05_t1_q01",
                    "teil": 1,
                    "prompt_zh": "女士乘几路有轨电车？",
                    "question_de": "Welche Straßenbahn nimmt die Frau?",
                    "options": [
                        {"key": "A", "text": "Tram 3"},
                        {"key": "B", "text": "Tram 7"},
                        {"key": "C", "text": "Tram 16"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Fährt die Straßenbahn 3 zum Südfriedhof? - Nein, dafür müssen Sie die Tram 7 nehmen. Die fährt alle 10 Minuten. - Vielen Dank!",
                    "transcript_de": "Fährt die Straßenbahn 3 zum Südfriedhof? - Nein, dafür müssen Sie die Tram 7 nehmen. Die fährt alle 10 Minuten. - Vielen Dank!",
                    "transcript_zh": "3路有轨电车去南公墓吗？- 不，您得坐7路有轨电车。每10分钟一趟。- 非常感谢！",
                    "key_vocabulary": [{"word": "die Straßenbahn", "plural": "die Straßenbahnen", "meaning": "有轨电车"}],
                    "explanation_zh": "明确指明要坐7路（'müssen Sie die Tram 7 nehmen'），选 B。"
                },
                {
                    "id": "a1_h_05_t1_q02",
                    "teil": 1,
                    "prompt_zh": "男士买了一双什么颜色的鞋子？",
                    "question_de": "Welche Farbe haben die Schuhe?",
                    "options": [
                        {"key": "A", "text": "Schwarz"},
                        {"key": "B", "text": "Braun"},
                        {"key": "C", "text": "Blau"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Gefallen Ihnen die braunen Schuhe? - Die braunen sind schön, aber für die Arbeit nehme ich die klassischen schwarzen in Größe 42.",
                    "transcript_de": "Gefallen Ihnen die braunen Schuhe? - Die braunen sind schön, aber für die Arbeit nehme ich die klassischen schwarzen in Größe 42.",
                    "transcript_zh": "您喜欢这双棕色的鞋吗？- 棕色的挺漂亮，但为了上班我还是拿这双经典的黑色42码。",
                    "key_vocabulary": [{"word": "die Farbe", "meaning": "颜色"}, {"word": "schwarz", "meaning": "黑色的"}],
                    "explanation_zh": "男士决定买黑色款（'die klassischen schwarzen'），选 A。"
                },
                {
                    "id": "a1_h_05_t1_q03",
                    "teil": 1,
                    "prompt_zh": "药店星期六几点营业？",
                    "question_de": "Wann hat die Apotheke am Samstag geöffnet?",
                    "options": [
                        {"key": "A", "text": "Von 8:30 bis 13:00 Uhr"},
                        {"key": "B", "text": "Von 9:00 bis 18:00 Uhr"},
                        {"key": "C", "text": "Samstags geschlossen"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Haben Sie am Samstagnachmittag auf? - Nein, samstags sind wir nur von 8:30 Uhr bis 13:00 Uhr für Sie da.",
                    "transcript_de": "Haben Sie am Samstagnachmittag auf? - Nein, samstags sind wir nur von 8:30 Uhr bis 13:00 Uhr für Sie da.",
                    "transcript_zh": "您周六下午开门吗？- 不开，周六我们只在上午8:30到13:00为您服务。",
                    "key_vocabulary": [{"word": "die Apotheke", "meaning": "药店"}],
                    "explanation_zh": "时间为 8:30 至 13:00，选 A。"
                },
                {
                    "id": "a1_h_05_t1_q04",
                    "teil": 1,
                    "prompt_zh": "女士租房需要找几居室的公寓？",
                    "question_de": "Wie viele Zimmer sucht die Frau?",
                    "options": [
                        {"key": "A", "text": "Eine 1-Zimmer-Wohnung"},
                        {"key": "B", "text": "Eine 2-Zimmer-Wohnung"},
                        {"key": "C", "text": "Eine 3-Zimmer-Wohnung"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Suchen Sie eine Wohnung alleine? - Nein, für mich und meinen Mann suchen wir eine gemütliche 2-Zimmer-Wohnung mit Balkon.",
                    "transcript_de": "Suchen Sie eine Wohnung alleine? - Nein, für mich und meinen Mann suchen wir eine gemütliche 2-Zimmer-Wohnung mit Balkon.",
                    "transcript_zh": "您一个人租房吗？- 不，我和我丈夫想找一套带阳台的温馨两居室公寓。",
                    "key_vocabulary": [{"word": "der Balkon", "meaning": "阳台"}],
                    "explanation_zh": "明确寻找两居室（'eine gemütliche 2-Zimmer-Wohnung'），选 B。"
                },
                {
                    "id": "a1_h_05_t1_q05",
                    "teil": 1,
                    "prompt_zh": "男士今晚点了什么主食？",
                    "question_de": "Was bestellt der Mann?",
                    "options": [
                        {"key": "A", "text": "Pizza Margherita"},
                        {"key": "B", "text": "Spaghetti Bolognese"},
                        {"key": "C", "text": "Fisch mit Reis"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Was darf ich Ihnen bringen? - Ich nehme bitte die Spaghetti Bolognese und dazu einen kleinen gemischten Salat.",
                    "transcript_de": "Was darf ich Ihnen bringen? - Ich nehme bitte die Spaghetti Bolognese und dazu einen kleinen gemischten Salat.",
                    "transcript_zh": "您需要点什么？- 请给我一份肉酱意面，外加一份小份混合沙拉。",
                    "key_vocabulary": [{"word": "bestellen", "meaning": "点餐，预订"}],
                    "explanation_zh": "男士点单 'Spaghetti Bolognese'，选 B。"
                },
                {
                    "id": "a1_h_05_t1_q06",
                    "teil": 1,
                    "prompt_zh": "两个人打算周末去哪里郊游？",
                    "question_de": "Wohin fahren die beiden am Wochenende?",
                    "options": [
                        {"key": "A", "text": "An die Nordsee"},
                        {"key": "B", "text": "In die Berge"},
                        {"key": "C", "text": "An den See"}
                    ],
                    "answer_key": "C",
                    "repeat_count": 2,
                    "audio_text_de": "Wollen wir am Sonntag in die Berge wandern? - Nein, das Wetter wird sehr heiß. Lass uns lieber an den See fahren und schwimmen.",
                    "transcript_de": "Wollen wir am Sonntag in die Berge wandern? - Nein, das Wetter wird sehr heiß. Lass uns lieber an den See fahren und schwimmen.",
                    "transcript_zh": "我们周日去山里徒步吗？- 不，天气会很热。我们还是去湖边游泳吧。",
                    "key_vocabulary": [{"word": "der See", "meaning": "湖泊"}],
                    "explanation_zh": "决定去湖边（'an den See fahren und schwimmen'），选 C。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_h_05_t2_q07",
                    "teil": 2,
                    "prompt_zh": "列车到达终点站，所有乘客必须下车。",
                    "question_de": "Der Zug endet hier und alle Fahrgäste müssen aussteigen.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Endstation: Dieser Zug endet hier. Wir bitten alle Fahrgäste auszusteigen und wünschen Ihnen einen schönen Tag.",
                    "transcript_de": "Endstation: Dieser Zug endet hier. Wir bitten alle Fahrgäste auszusteigen und wünschen Ihnen einen schönen Tag.",
                    "transcript_zh": "终点站播报：本列车到达终点站。请所有旅客下车，祝您度过愉快的一天。",
                    "key_vocabulary": [{"word": "die Endstation", "meaning": "终点站"}],
                    "explanation_zh": "广播说明终点站全体下车，陈述正确，选 R。"
                },
                {
                    "id": "a1_h_05_t2_q08",
                    "teil": 2,
                    "prompt_zh": "机场免税店今天消费满 50 欧元送旅行包。",
                    "question_de": "Im Duty-Free-Shop gibt es heute ab 50 Euro Einkaufswert eine Tasche geschenkt.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Sonderaktion am Flughafen: Beim Einkauf ab 50 Euro in unserem Duty-Free-Shop erhalten Sie eine hochwertige Reisetasche gratis dazu.",
                    "transcript_de": "Sonderaktion am Flughafen: Beim Einkauf ab 50 Euro in unserem Duty-Free-Shop erhalten Sie eine hochwertige Reisetasche gratis dazu.",
                    "transcript_zh": "机场特别活动：凡在我们免税店购物满50欧元，即可免费获赠高品质旅行包一个。",
                    "key_vocabulary": [{"word": "gratis", "meaning": "免费的，赠送的"}],
                    "explanation_zh": "广播确认满50欧赠送旅行包（Reisetasche gratis），陈述正确，选 R。"
                },
                {
                    "id": "a1_h_05_t2_q09",
                    "teil": 2,
                    "prompt_zh": "博物馆今天免费提供语音导览器。",
                    "question_de": "Der Audioguide im Museum kostet heute extra 5 Euro.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "F",
                    "repeat_count": 1,
                    "audio_text_de": "Liebe Museumsgäste: Heute zum internationalen Museumstag ist die Nutzung aller Audioguides für Sie komplett kostenlos.",
                    "transcript_de": "Liebe Museumsgäste: Heute zum internationalen Museumstag ist die Nutzung aller Audioguides für Sie komplett kostenlos.",
                    "transcript_zh": "亲爱的博物馆观众：今天恰逢国际博物馆日，所有语音导览器的使用对您完全免费。",
                    "key_vocabulary": [{"word": "der Audioguide", "meaning": "语音导览器"}],
                    "explanation_zh": "广播说是完全免费（komplett kostenlos），并非额外收费5欧元，故选 F。"
                },
                {
                    "id": "a1_h_05_t2_q10",
                    "teil": 2,
                    "prompt_zh": "超市面包房在下午 18 点后所有面包半价。",
                    "question_de": "In der Bäckerei gibt es ab 18 Uhr alle Brote zum halben Preis.",
                    "options": [
                        {"key": "R", "text": "Richtig (正确)"},
                        {"key": "F", "text": "Falsch (错误)"}
                    ],
                    "answer_key": "R",
                    "repeat_count": 1,
                    "audio_text_de": "Feierabend-Angebot: Ab 18 Uhr erhalten Sie in unserer Bäckerei alle frischen Brote und Brötchen zum halben Preis.",
                    "transcript_de": "Feierabend-Angebot: Ab 18 Uhr erhalten Sie in unserer Bäckerei alle frischen Brote und Brötchen zum halben Preis.",
                    "transcript_zh": "下班晚间特惠：18点起，我们面包房的所有新鲜面包和小面包均半价销售。",
                    "key_vocabulary": [{"word": "das Brötchen", "plural": "die Brötchen", "meaning": "小面包"}],
                    "explanation_zh": "广播说明18点后半价，陈述正确，选 R。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_h_05_t3_q11",
                    "teil": 3,
                    "prompt_zh": "租房房东约定的看房时间是几点？",
                    "question_de": "Um wie viel Uhr ist der Besichtigungstermin?",
                    "options": [
                        {"key": "A", "text": "Um 16:30 Uhr"},
                        {"key": "B", "text": "Um 17:30 Uhr"},
                        {"key": "C", "text": "Um 18:30 Uhr"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Hallo Herr Wagner, Vermieter Weber hier. Der Besichtigungstermin für die Wohnung ist am Freitag pünktlich um 17:30 Uhr.",
                    "transcript_de": "Hallo Herr Wagner, Vermieter Weber hier. Der Besichtigungstermin für die Wohnung ist am Freitag pünktlich um 17:30 Uhr.",
                    "transcript_zh": "瓦格纳先生您好，我是房东韦伯。公寓看房时间定于周五准时17:30。",
                    "key_vocabulary": [{"word": "der Besichtigungstermin", "meaning": "看房约会"}],
                    "explanation_zh": "看房时间为 17:30（'um 17:30 Uhr'），选 B。"
                },
                {
                    "id": "a1_h_05_t3_q12",
                    "teil": 3,
                    "prompt_zh": "德语强化班开班日期是几号？",
                    "question_de": "Wann beginnt der Deutsch-Intensivkurs?",
                    "options": [
                        {"key": "A", "text": "Am 1. September"},
                        {"key": "B", "text": "Am 15. September"},
                        {"key": "C", "text": "Am 1. Oktober"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Sprachenzentrum Info: Der neue Deutsch-Intensivkurs A1 beginnt am Montag, den 15. September um 9:00 Uhr in Raum 12.",
                    "transcript_de": "Sprachenzentrum Info: Der neue Deutsch-Intensivkurs A1 beginnt am Montag, den 15. September um 9:00 Uhr in Raum 12.",
                    "transcript_zh": "语言中心通知：新的德语A1强化班将于9月15日周一上午9:00在12教室开班。",
                    "key_vocabulary": [{"word": "der Intensivkurs", "meaning": "强化课程"}],
                    "explanation_zh": "开课日期为 9月15日（'den 15. September'），选 B。"
                },
                {
                    "id": "a1_h_05_t3_q13",
                    "teil": 3,
                    "prompt_zh": "丢失的手提包被送到了哪里？",
                    "question_de": "Wo wurde die verlorene Handtasche abgegeben?",
                    "options": [
                        {"key": "A", "text": "Im Fundbüro am Bahnhof"},
                        {"key": "B", "text": "Bei der Polizei"},
                        {"key": "C", "text": "An der Hotelrezeption"}
                    ],
                    "answer_key": "A",
                    "repeat_count": 2,
                    "audio_text_de": "Guten Tag Frau Berger, hier ist das Fundbüro der Deutschen Bahn am Hauptbahnhof. Ihre schwarze Handtasche wurde bei uns abgegeben.",
                    "transcript_de": "Guten Tag Frau Berger, hier ist das Fundbüro der Deutschen Bahn am Hauptbahnhof. Ihre schwarze Handtasche wurde bei uns abgegeben.",
                    "transcript_zh": "贝尔格女士您好，这里是火车总站的德国铁路失物招领处。您的黑色手提包已被送到我们这里。",
                    "key_vocabulary": [{"word": "das Fundbüro", "meaning": "失物招领处"}],
                    "explanation_zh": "留言处为火车总站失物招领处（'das Fundbüro der Deutschen Bahn'），选 A。"
                },
                {
                    "id": "a1_h_05_t3_q14",
                    "teil": 3,
                    "prompt_zh": "去滑雪场的大巴车票往返多少钱？",
                    "question_de": "Wie viel kostet das Busticket hin und zurück?",
                    "options": [
                        {"key": "A", "text": "18 Euro"},
                        {"key": "B", "text": "28 Euro"},
                        {"key": "C", "text": "38 Euro"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Skibus-Express: Die Hin- und Rückfahrt in die Alpen kostet für Erwachsene 28 Euro und für Kinder 15 Euro.",
                    "transcript_de": "Skibus-Express: Die Hin- und Rückfahrt in die Alpen kostet für Erwachsene 28 Euro und für Kinder 15 Euro.",
                    "transcript_zh": "滑雪大巴快线：前往阿尔卑斯山的往返车票成人28欧元，儿童15欧元。",
                    "key_vocabulary": [{"word": "die Hin- und Rückfahrt", "meaning": "往返行程"}],
                    "explanation_zh": "往返成人票价为 28 欧元（'28 Euro'），选 B。"
                },
                {
                    "id": "a1_h_05_t3_q15",
                    "teil": 3,
                    "prompt_zh": "火警紧急电话是多少？",
                    "question_de": "Wie lautet die Notrufnummer für die Feuerwehr?",
                    "options": [
                        {"key": "A", "text": "110"},
                        {"key": "B", "text": "112"},
                        {"key": "C", "text": "115"}
                    ],
                    "answer_key": "B",
                    "repeat_count": 2,
                    "audio_text_de": "Wichtiger Sicherheitshinweis: Im Brandfall oder bei medizinischen Notfällen wählen Sie bitte sofort die europäische Notrufnummer 112.",
                    "transcript_de": "Wichtiger Sicherheitshinweis: Im Brandfall oder bei medizinischen Notfällen wählen Sie bitte sofort die europäische Notrufnummer 112.",
                    "transcript_zh": "重要安全提示：发生火灾或医疗紧急情况时，请立即拨打欧洲急救电话 112。",
                    "key_vocabulary": [{"word": "die Feuerwehr", "meaning": "消防队"}, {"word": "der Notfall", "meaning": "紧急情况"}],
                    "explanation_zh": "消防与急救电话为 112（110 为警察局），选 B。"
                }
            ]
        }
    }
]

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

def get_hoeren_set_list() -> List[Dict[str, Any]]:
    """返回 5 套 A1 听力试卷元数据列表"""
    return [
        {
            "set_id": s["set_id"],
            "title_de": s["title_de"],
            "title_zh": s["title_zh"],
            "total_questions": s["total_questions"]
        }
        for s in A1_HOEREN_SETS
    ]


def get_hoeren_set_by_id(set_id: int, sanitize: bool = True) -> Optional[Dict[str, Any]]:
    """获取指定套题内容。sanitize=True 时剔除答案与解析以防作弊"""
    target = None
    for s in A1_HOEREN_SETS:
        if s["set_id"] == set_id:
            target = s
            break
    if not target:
        return None

    if not sanitize:
        return target

    # 深度拷贝并脱敏
    sanitized_parts = {}
    for part_name, questions in target["parts"].items():
        clean_questions = []
        for q in questions:
            clean_q = {
                "id": q["id"],
                "teil": q["teil"],
                "prompt_zh": q["prompt_zh"],
                "question_de": q["question_de"],
                "options": q["options"],
                "repeat_count": q["repeat_count"],
                "audio_text_de": q["audio_text_de"],
                "key_vocabulary": q.get("key_vocabulary", [])
            }
            clean_questions.append(clean_q)
        sanitized_parts[part_name] = clean_questions

    return {
        "set_id": target["set_id"],
        "title_de": target["title_de"],
        "title_zh": target["title_zh"],
        "total_questions": target["total_questions"],
        "parts": sanitized_parts
    }


def grade_hoeren_answers(set_id: int, user_answers: Dict[str, str]) -> Dict[str, Any]:
    """
    批改 A1 听力答题，计算 25 分制官方得分与等级：
    20.0 ~ 25.0: Sehr gut (优秀)
    17.5 ~ 19.9: Gut (良好)
    15.0 ~ 17.4: Befriedigend (中等)
    12.5 ~ 14.9: Ausreichend (及格)
    < 12.5:      Nicht bestanden (未通过)
    """
    raw_set = get_hoeren_set_by_id(set_id, sanitize=False)
    if not raw_set:
        return {
            "error": "Set not found",
            "score_raw": 0,
            "score_official": 0.0,
            "rating": "Nicht bestanden",
            "wrong_questions": [],
            "details": []
        }

    correct_count = 0
    wrong_questions = []
    details = []

    for part_name in ("teil_1", "teil_2", "teil_3"):
        for q in raw_set["parts"].get(part_name, []):
            qid = q["id"]
            user_ans = user_answers.get(qid, "").strip().upper()
            correct_ans = q["answer_key"].strip().upper()
            is_correct = (user_ans == correct_ans)

            if is_correct:
                correct_count += 1
            else:
                wrong_questions.append(qid)

            details.append({
                "id": qid,
                "teil": q["teil"],
                "user_answer": user_ans,
                "correct_answer": correct_ans,
                "is_correct": is_correct,
                "transcript_de": q["transcript_de"],
                "transcript_zh": q["transcript_zh"],
                "explanation_zh": q["explanation_zh"],
                "key_vocabulary": q.get("key_vocabulary", [])
            })

    total_q = raw_set["total_questions"]
    score_official = round((correct_count / float(total_q)) * 25.0, 1)

    if score_official >= 20.0:
        rating = "Sehr gut"
    elif score_official >= 17.5:
        rating = "Gut"
    elif score_official >= 15.0:
        rating = "Befriedigend"
    elif score_official >= 12.5:
        rating = "Ausreichend"
    else:
        rating = "Nicht bestanden"

    return {
        "set_id": set_id,
        "score_raw": correct_count,
        "total_questions": total_q,
        "score_official": score_official,
        "rating": rating,
        "wrong_questions": wrong_questions,
        "details": details
    }
