"""
DeLector - Goethe-Zertifikat A1 Lesen (Reading) Exam Dataset & Engine
Contains 6 authentic Goethe A1 model test sets (15 questions per set, 90 questions total).
Teil 1: 5 questions (Kurze Mitteilungen/E-Mails · Richtig/Falsch)
Teil 2: 5 questions (Zwei Web-Anzeigen/Angebote im Vergleich · A / B)
Teil 3: 5 questions (Schilder & Aushänge im Alltag · Richtig/Falsch)
"""

from typing import List, Dict, Any, Optional

# ─────────────────────────────────────────────────────────────────────────────
# 6 Full A1 Reading Exam Sets (Modellsatz 01 - 06)
# ─────────────────────────────────────────────────────────────────────────────

A1_LESEN_SETS: List[Dict[str, Any]] = [
    # ── SET 01 ──────────────────────────────────────────────────────────────
    {
        "set_id": 1,
        "title_de": "Goethe-Zertifikat A1 Lesen Modellsatz 01",
        "title_zh": "歌德 A1 官方阅读全真卷 01",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_l_01_t1_q01",
                    "teil": 1,
                    "reading_text_de": "Liebe Eva, vielen Dank für deine Einladung zum Geburtstag. Ich komme sehr gern am Samstagabend um 19:00 Uhr zu dir. Soll ich einen Kuchen oder Wein mitbringen? Herzliche Grüße, Maria",
                    "statement_de": "Maria kommt am Samstag zur Geburtstagsparty von Eva.",
                    "statement_zh": "玛丽亚周六去参加伊娃的生日聚会。",
                    "answer_key": "R",
                    "explanation_zh": "邮件中 Maria 明确写道：'Ich komme sehr gern am Samstagabend... zu dir'，陈述正确，选 R。"
                },
                {
                    "id": "a1_l_01_t1_q02",
                    "teil": 1,
                    "reading_text_de": "Liebe Eva, vielen Dank für deine Einladung zum Geburtstag. Ich komme sehr gern am Samstagabend um 19:00 Uhr zu dir. Soll ich einen Kuchen oder Wein mitbringen? Herzliche Grüße, Maria",
                    "statement_de": "Eva soll einen Kuchen backen.",
                    "statement_zh": "伊娃应该烤一个蛋糕。",
                    "answer_key": "F",
                    "explanation_zh": "是 Maria 询问自己是否要带蛋糕（'Soll ich einen Kuchen... mitbringen?'），而非让 Eva 烤，故选 F。"
                },
                {
                    "id": "a1_l_01_t1_q03",
                    "teil": 1,
                    "reading_text_de": "Sehr geehrte Frau Müller, mein Sohn Felix kann heute leider nicht am Schwimmunterricht teilnehmen. Er hat starke Halsschmerzen und der Arzt hat ihm Ruhe verordnet. Mit freundlichen Grüßen, Thomas Weber",
                    "statement_de": "Felix geht heute zum Schwimmunterricht.",
                    "statement_zh": "菲利克斯今天去上游泳课。",
                    "answer_key": "F",
                    "explanation_zh": "父亲说明儿子不能参加（'kann heute leider nicht am Schwimmunterricht teilnehmen'），选 F。"
                },
                {
                    "id": "a1_l_01_t1_q04",
                    "teil": 1,
                    "reading_text_de": "Sehr geehrte Frau Müller, mein Sohn Felix kann heute leider nicht am Schwimmunterricht teilnehmen. Er hat starke Halsschmerzen und der Arzt hat ihm Ruhe verordnet. Mit freundlichen Grüßen, Thomas Weber",
                    "statement_de": "Felix ist krank.",
                    "statement_zh": "菲利克斯生病了。",
                    "answer_key": "R",
                    "explanation_zh": "信中提到他咽喉剧痛并看过了医生（'starke Halsschmerzen'），陈述正确，选 R。"
                },
                {
                    "id": "a1_l_01_t1_q05",
                    "teil": 1,
                    "reading_text_de": "Hallo Tim, ich habe meine Jacke in deinem Auto vergessen. Die schwarze mit der Kapuze. Kannst du sie mir morgen zur Arbeit mitbringen? Danke dir! LG Jonas",
                    "statement_de": "Jonas sucht seine schwarze Jacke.",
                    "statement_zh": "约纳斯在找他的黑色夹克。",
                    "answer_key": "R",
                    "explanation_zh": "Jonas 遗落了夹克并请对方带来（'habe meine Jacke in deinem Auto vergessen'），陈述正确，选 R。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_l_01_t2_q06",
                    "teil": 2,
                    "user_need_zh": "您想在周末租一辆自行车去湖边骑行。",
                    "ad_a": {
                        "title": "www.city-bike-verleih.de",
                        "text_de": "Fahrradverleih am Bahnhof: Trekking- und Citybikes ab 12 € pro Tag. Auch am Samstag und Sonntag geöffnet von 9 bis 18 Uhr."
                    },
                    "ad_b": {
                        "title": "www.motorrad-shop-mueller.de",
                        "text_de": "Verkauf und Reparatur von Motorrädern und Motorrollern. Mo-Fr 8-17 Uhr. Kein Fahrradverleih."
                    },
                    "answer_key": "A",
                    "explanation_zh": "网站 A 提供周末自行车租赁（Trekking- und Citybikes ab 12 €），网站 B 是摩托车店且不提供自行车租赁，故选 A。"
                },
                {
                    "id": "a1_l_01_t2_q07",
                    "teil": 2,
                    "user_need_zh": "您想在晚上学习德语 A1 课程。",
                    "ad_a": {
                        "title": "www.vhs-deutschkurse.de",
                        "text_de": "Abendkurse Deutsch als Fremdsprache A1: Dienstag und Donnerstag von 18:30 bis 20:30 Uhr. Anmeldung online möglich."
                    },
                    "ad_b": {
                        "title": "www.sprachcamp-kinder.de",
                        "text_de": "Deutsch-Feriencamp für Schulkinder von 8 bis 14 Jahren. Täglich von 9:00 bis 15:00 Uhr in den Sommerferien."
                    },
                    "answer_key": "A",
                    "explanation_zh": "网站 A 提供晚上 A1 德语晚班（Abendkurse 18:30-20:30），网站 B 为儿童假期白班夏令营，故选 A。"
                },
                {
                    "id": "a1_l_01_t2_q08",
                    "teil": 2,
                    "user_need_zh": "您在寻找一家周日中午营业的传统意大利餐厅。",
                    "ad_a": {
                        "title": "www.ristorante-roma.de",
                        "text_de": "Original italienische Pizza und Pasta. Geöffnet: Dienstag bis Sonntag durchgehend von 11:30 bis 22:00 Uhr."
                    },
                    "ad_b": {
                        "title": "www.asia-bistro-mai.de",
                        "text_de": "Asiatische Spezialitäten und Nudelgerichte. Mo-Sa 11-20 Uhr. Sonntags Ruhetag."
                    },
                    "answer_key": "A",
                    "explanation_zh": "Roma 餐厅为意大利风味且周日营业（Dienstag bis Sonntag ab 11:30），B 为亚洲快餐且周日休息，选 A。"
                },
                {
                    "id": "a1_l_01_t2_q09",
                    "teil": 2,
                    "user_need_zh": "您想在柏林市中心预订一间带无线网的双人客房。",
                    "ad_a": {
                        "title": "www.campingplatz-berlin-gruen.de",
                        "text_de": "Zeltplatz und Stellplätze für Wohnmobile am Stadtrand von Berlin. Sanitäranlagen vorhanden. Kein Hotelbetrieb."
                    },
                    "ad_b": {
                        "title": "www.hotel-berlin-mitte.de",
                        "text_de": "Komfortable Doppelzimmer im Zentrum Berlins. Kostenloses Highspeed-WLAN und Frühstücksbuffet inklusive."
                    },
                    "answer_key": "B",
                    "explanation_zh": "网站 B 是市中心的舒适双人房并含免费 WLAN（Doppelzimmer im Zentrum），A 是郊外露营帐篷营地，选 B。"
                },
                {
                    "id": "a1_l_01_t2_q10",
                    "teil": 2,
                    "user_need_zh": "您想买一张去法兰克福的特价火车票。",
                    "ad_a": {
                        "title": "www.bahn.de/sparpreis",
                        "text_de": "Mit dem Sparpreis der Bahn günstig durch ganz Deutschland reisen. ICE-Tickets nach Frankfurt ab 19,90 Euro buchen."
                    },
                    "ad_b": {
                        "title": "www.taxi-ruf-zentrale.de",
                        "text_de": "Ihr 24-Stunden-Taxiservice im Stadtgebiet. Flughafen- und Bahnhofstransfer zum Festpreis."
                    },
                    "answer_key": "A",
                    "explanation_zh": "网站 A 提供德国铁路去法兰克福的特价火车票（ICE-Tickets ab 19,90 Euro），B 为市内出租车，选 A。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_l_01_t3_q11",
                    "teil": 3,
                    "sign_text_de": "Bitte die Tür immer geschlossen halten! Danke. Die Hausverwaltung.",
                    "statement_de": "Die Tür soll nach dem Durchgehen zugemacht werden.",
                    "statement_zh": "进出后应该把门关好。",
                    "answer_key": "R",
                    "explanation_zh": "标牌要求 'immer geschlossen halten'（时刻保持关闭），陈述正确，选 R。"
                },
                {
                    "id": "a1_l_01_t3_q12",
                    "teil": 3,
                    "sign_text_de": "Notausgang! Bitte freihalten! Keine Fahrräder abstellen!",
                    "statement_de": "Hier darf man sein Fahrrad parken.",
                    "statement_zh": "这里可以停放自行车。",
                    "answer_key": "F",
                    "explanation_zh": "标牌写明 'Keine Fahrräder abstellen!'（严禁停放自行车），陈述与标牌相反，选 F。"
                },
                {
                    "id": "a1_l_01_t3_q13",
                    "teil": 3,
                    "sign_text_de": "Bibliothek: Samstags und sonntags geschlossen. Mo-Fr 9:00 - 18:00 Uhr.",
                    "statement_de": "Die Bibliothek ist am Wochenende nicht geöffnet.",
                    "statement_zh": "图书馆周末不开放。",
                    "answer_key": "R",
                    "explanation_zh": "标牌说明周六周日关闭（Samstags und sonntags geschlossen），即周末不开放，选 R。"
                },
                {
                    "id": "a1_l_01_t3_q14",
                    "teil": 3,
                    "sign_text_de": "Supermarkt-Kasse: Nur Barzahlung möglich! Keine Kartenzahlung.",
                    "statement_de": "Sie können hier mit EC-Karte oder Kreditkarte bezahlen.",
                    "statement_zh": "您可以在这里用储蓄卡或信用卡付款。",
                    "answer_key": "F",
                    "explanation_zh": "标牌强调只能现金支付（Nur Barzahlung，Keine Kartenzahlung），陈述错误，选 F。"
                },
                {
                    "id": "a1_l_01_t3_q15",
                    "teil": 3,
                    "sign_text_de": "Aufzug defekt! Bitte die Treppe benutzen.",
                    "statement_de": "Der Aufzug funktioniert heute nicht.",
                    "statement_zh": "电梯今天故障无法使用。",
                    "answer_key": "R",
                    "explanation_zh": "标牌写明 'Aufzug defekt'（电梯损坏），陈述正确，选 R。"
                }
            ]
        }
    },

    # ── SET 02 ──────────────────────────────────────────────────────────────
    {
        "set_id": 2,
        "title_de": "Goethe-Zertifikat A1 Lesen Modellsatz 02",
        "title_zh": "歌德 A1 官方阅读全真卷 02",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_l_02_t1_q01",
                    "teil": 1,
                    "reading_text_de": "Lieber Markus, wir treffen uns heute nicht im Restaurant Stern, sondern bei mir zu Hause in der Gartenstraße 12. Bring bitte deine Musikbox mit! Bis später, Stefan",
                    "statement_de": "Das Treffen findet bei Stefan zu Hause statt.",
                    "statement_zh": "聚会在斯特凡家里举行。",
                    "answer_key": "R",
                    "explanation_zh": "Stefan 说明改在 'bei mir zu Hause' 见面，选 R。"
                },
                {
                    "id": "a1_l_02_t1_q02",
                    "teil": 1,
                    "reading_text_de": "Lieber Markus, wir treffen uns heute nicht im Restaurant Stern, sondern bei mir zu Hause in der Gartenstraße 12. Bring bitte deine Musikbox mit! Bis später, Stefan",
                    "statement_de": "Markus soll Essen mitbringen.",
                    "statement_zh": "马库斯应该带吃的过去。",
                    "answer_key": "F",
                    "explanation_zh": "要求带的是音响（'deine Musikbox'），而非食物，选 F。"
                },
                {
                    "id": "a1_l_02_t1_q03",
                    "teil": 1,
                    "reading_text_de": "Guten Tag Herr Braun, Ihr Fahrrad ist repariert. Neue Reifen und Bremsen sind montiert. Die Kosten betragen 45 Euro. Bitte holen Sie es bis Freitag ab. Fahrradwerkstatt Schnell",
                    "statement_de": "Das Fahrrad von Herrn Braun ist fertig.",
                    "statement_zh": "布劳恩先生的自行车修好了。",
                    "answer_key": "R",
                    "explanation_zh": "修车行通知 'Ihr Fahrrad ist repariert'，选 R。"
                },
                {
                    "id": "a1_l_02_t1_q04",
                    "teil": 1,
                    "reading_text_de": "Guten Tag Herr Braun, Ihr Fahrrad ist repariert. Neue Reifen und Bremsen sind montiert. Die Kosten betragen 45 Euro. Bitte holen Sie es bis Freitag ab. Fahrradwerkstatt Schnell",
                    "statement_de": "Herr Braun muss 100 Euro bezahlen.",
                    "statement_zh": "布劳恩先生必须支付100欧元。",
                    "answer_key": "F",
                    "explanation_zh": "费用为 45 欧元（'betragen 45 Euro'），选 F。"
                },
                {
                    "id": "a1_l_02_t1_q05",
                    "teil": 1,
                    "reading_text_de": "Liebe Kollegen, am Freitag ab 16 Uhr feiern wir unseren Betriebsausflug im Park. Getränke und Grillgut sind kostenlos für alle Mitarbeiter da. VG Personalrat",
                    "statement_de": "Die Mitarbeiter müssen für Getränke bezahlen.",
                    "statement_zh": "员工必须自费购买饮料。",
                    "answer_key": "F",
                    "explanation_zh": "通知写明饮料与烧烤对员工免费（'kostenlos für alle Mitarbeiter'），选 F。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_l_02_t2_q06",
                    "teil": 2,
                    "user_need_zh": "您想在周六上午买新鲜的蔬菜和水果。",
                    "ad_a": {
                        "title": "www.wochenmarkt-am-dom.de",
                        "text_de": "Traditioneller Wochenmarkt: Jeden Samstag 7 bis 13 Uhr. Frisches regionales Obst, Gemüse, Käse und Blumen."
                    },
                    "ad_b": {
                        "title": "www.moebelhaus-xxl.de",
                        "text_de": "Möbel und Wohnaccessoires. Große Küchenausstellung. Mo-Sa 10-20 Uhr."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是周六上午的蔬果市集（Wochenmarkt Samstag 7-13 Uhr），B 是家具店，选 A。"
                },
                {
                    "id": "a1_l_02_t2_q07",
                    "teil": 2,
                    "user_need_zh": "您想给您的猫看病。",
                    "ad_a": {
                        "title": "www.tierarztpraxis-dr-fischer.de",
                        "text_de": "Tierärztliche Praxis für Kleintiere, Hunde und Katzen. Notdienst rund um die Uhr. Mo-Fr 8-19 Uhr, Sa 9-12 Uhr."
                    },
                    "ad_b": {
                        "title": "www.zahnarzt-fischer.de",
                        "text_de": "Moderne Zahnmedizin für die ganze Familie. Schmerzbehandlung und Prophylaxe."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是针对猫狗的宠物兽医诊所（Tierarztpraxis Hunde und Katzen），B 为人类牙医，选 A。"
                },
                {
                    "id": "a1_l_02_t2_q08",
                    "teil": 2,
                    "user_need_zh": "您想报名参加每周一晚上的瑜伽初级班。",
                    "ad_a": {
                        "title": "www.sportverein-aktiv.de",
                        "text_de": "Fußball- und Basketball-Training für Jugendliche. Montag 18 Uhr Sportplatz West."
                    },
                    "ad_b": {
                        "title": "www.yoga-studio-shanti.de",
                        "text_de": "Yoga für Anfänger: Montags 19:00 bis 20:15 Uhr. Entspannung und Körperhaltung. Probestunde gratis."
                    },
                    "answer_key": "B",
                    "explanation_zh": "B 是周一晚上的初学者瑜伽班（Yoga für Anfänger Montags 19:00），A 为青少年足球篮球，选 B。"
                },
                {
                    "id": "a1_l_02_t2_q09",
                    "teil": 2,
                    "user_need_zh": "您想把一件羊毛大衣送去专业干洗。",
                    "ad_a": {
                        "title": "www.textilreinigung-sauber.de",
                        "text_de": "Professionelle chemische Reinigung für Anzüge, Kleider und Wollmäntel. Express-Service innerhalb 24 Stunden."
                    },
                    "ad_b": {
                        "title": "www.schuhmacher-meister.de",
                        "text_de": "Schuhreparatur, Schlüsselnotdienst und Lederpflege. Schnelle Reparatur Ihrer Lieblingsschuhe."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是专业的衣服干洗店（chemische Reinigung für Wollmäntel），B 是修鞋配钥匙铺，选 A。"
                },
                {
                    "id": "a1_l_02_t2_q10",
                    "teil": 2,
                    "user_need_zh": "您想买一本二手的德语 A1 语法书。",
                    "ad_a": {
                        "title": "www.antik-moebel-shop.de",
                        "text_de": "Ankauf und Verkauf von antiken Schränken, Tischen und Lampen aus dem 19. Jahrhundert."
                    },
                    "ad_b": {
                        "title": "www.buecher-flohmarkt.de",
                        "text_de": "Gebrauchte Bücher, Lehrbücher und Sprachführer zu günstigen Preisen. Deutschkurse A1-B2 ab 3 Euro."
                    },
                    "answer_key": "B",
                    "explanation_zh": "B 是二手书市场（Gebrauchte Bücher, Lehrbücher），A 是古董家具店，选 B。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_l_02_t3_q11",
                    "teil": 3,
                    "sign_text_de": "Rauchen verboten! Im gesamten Gebäude gilt absolutes Rauchverbot.",
                    "statement_de": "Im Gebäude darf nicht geraucht werden.",
                    "statement_zh": "在建筑物内严禁吸烟。",
                    "answer_key": "R",
                    "explanation_zh": "标牌注明 'Rauchen verboten'（禁止吸烟），陈述正确，选 R。"
                },
                {
                    "id": "a1_l_02_t3_q12",
                    "teil": 3,
                    "sign_text_de": "Schwimmbad: Eintritt für Kinder unter 3 Jahren frei.",
                    "statement_de": "Babys und Kleinkinder unter 3 Jahren müssen Eintritt bezahlen.",
                    "statement_zh": "3岁以下婴幼儿必须购买门票。",
                    "answer_key": "F",
                    "explanation_zh": "标牌注明 3 岁以下免费（'Eintritt frei'），陈述说要付门票，错误，选 F。"
                },
                {
                    "id": "a1_l_02_t3_q13",
                    "teil": 3,
                    "sign_text_de": "Parkplatz nur für Kunden! Fremdparker werden kostenpflichtig abgeschleppt.",
                    "statement_de": "Jeder darf auf diesem Parkplatz kostenlos parken.",
                    "statement_zh": "任何人都可以在这个停车场免费停车。",
                    "answer_key": "F",
                    "explanation_zh": "该停车场仅限顾客使用（'nur für Kunden'），外来车辆会被拖走，选 F。"
                },
                {
                    "id": "a1_l_02_t3_q14",
                    "teil": 3,
                    "sign_text_de": "Vorsicht bissiger Hund! Betreten des Grundstücks auf eigene Gefahr!",
                    "statement_de": "Auf diesem Grundstück gibt es einen Hund.",
                    "statement_zh": "这块私有地产上有狗。",
                    "answer_key": "R",
                    "explanation_zh": "警告标牌明确提醒内有咬人烈犬（'bissiger Hund'），选 R。"
                },
                {
                    "id": "a1_l_02_t3_q15",
                    "teil": 3,
                    "sign_text_de": "Apotheken-Notdienst: Außerhalb der Öffnungszeiten bitte die Klingel an der Tür betätigen.",
                    "statement_de": "Im Notfall kann man auch nachts Medikamente bekommen.",
                    "statement_zh": "紧急情况下夜间也可以拿到药品。",
                    "answer_key": "R",
                    "explanation_zh": "急诊药店标牌注明非营业时间可按门铃，说明夜间急诊可用，选 R。"
                }
            ]
        }
    },

    # ── SET 03 ──────────────────────────────────────────────────────────────
    {
        "set_id": 3,
        "title_de": "Goethe-Zertifikat A1 Lesen Modellsatz 03",
        "title_zh": "歌德 A1 官方阅读全真卷 03",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_l_03_t1_q01",
                    "teil": 1,
                    "reading_text_de": "Liebe Sarah, ich lade dich herzlich zu meinem Einzugsfest in meine neue Wohnung ein. Wir feiern am Samstag ab 18 Uhr in der Hauptstraße 45. Bring gerne deinen Freund mit! Liebe Grüße, Anna",
                    "statement_de": "Anna feiert ihre neue Wohnung.",
                    "statement_zh": "安娜庆祝乔迁新居。",
                    "answer_key": "R",
                    "explanation_zh": "Anna 明确邀请参加乔迁派对（'Einzugsfest in meine neue Wohnung'），选 R。"
                },
                {
                    "id": "a1_l_03_t1_q02",
                    "teil": 1,
                    "reading_text_de": "Liebe Sarah, ich lade dich herzlich zu meinem Einzugsfest in meine neue Wohnung ein. Wir feiern am Samstag ab 18 Uhr in der Hauptstraße 45. Bring gerne deinen Freund mit! Liebe Grüße, Anna",
                    "statement_de": "Sarah darf nur alleine kommen.",
                    "statement_zh": "萨拉只能独自一人前往。",
                    "answer_key": "F",
                    "explanation_zh": "Anna 提到可以带男友一起（'Bring gerne deinen Freund mit'），选 F。"
                },
                {
                    "id": "a1_l_03_t1_q03",
                    "teil": 1,
                    "reading_text_de": "Sehr geehrter Herr Meyer, wir haben Ihre Waschmaschine erfolgreich repariert. Die Gesamtrechnung über 85 Euro können Sie bei Abholung bar oder mit Karte begleichen. Kundendienst Elektro-Fix",
                    "statement_de": "Die Waschmaschine funktioniert wieder.",
                    "statement_zh": "洗衣机修好了能正常运转了。",
                    "answer_key": "R",
                    "explanation_zh": "维修服务说明已成功修好（'erfolgreich repariert'），选 R。"
                },
                {
                    "id": "a1_l_03_t1_q04",
                    "teil": 1,
                    "reading_text_de": "Sehr geehrter Herr Meyer, wir haben Ihre Waschmaschine erfolgreich repariert. Die Gesamtrechnung über 85 Euro können Sie bei Abholung bar oder mit Karte begleichen. Kundendienst Elektro-Fix",
                    "statement_de": "Herr Meyer kann nur mit Bargeld bezahlen.",
                    "statement_zh": "迈尔先生只能用现金付款。",
                    "answer_key": "F",
                    "explanation_zh": "取货时可付现金或刷卡（'bar oder mit Karte'），选 F。"
                },
                {
                    "id": "a1_l_03_t1_q05",
                    "teil": 1,
                    "reading_text_de": "Hallo Bernd, kannst du mich heute um 16:30 Uhr vom Bahnhof abholen? Mein Koffer ist sehr schwer. Bis gleich, Lisa",
                    "statement_de": "Lisa bittet Bernd um Hilfe am Bahnhof.",
                    "statement_zh": "丽莎请求贝恩德在火车站接她帮忙。",
                    "answer_key": "R",
                    "explanation_zh": "Lisa 行李很重请求去火车站接她，选 R。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_l_03_t2_q06",
                    "teil": 2,
                    "user_need_zh": "您想带全家人去参观动物园并观看海豚表演。",
                    "ad_a": {
                        "title": "www.zoologischer-garten-stadt.de",
                        "text_de": "Erlebnis Zoo: Über 5000 Tiere, großes Aquarium und tägliche Fütterungsshows. Familienkarte 35 Euro."
                    },
                    "ad_b": {
                        "title": "www.botanischer-garten-flora.de",
                        "text_de": "Botanischer Garten: Tropische Pflanzen und seltene Blumen. Schöne Spazierwege. Keine Tiere."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是动物园（Zoo über 5000 Tiere），B 是植物园且明确无动物，选 A。"
                },
                {
                    "id": "a1_l_03_t2_q07",
                    "teil": 2,
                    "user_need_zh": "您想在周末学习制作正宗的德国黑森林蛋糕。",
                    "ad_a": {
                        "title": "www.backschule-suess.de",
                        "text_de": "Backkurse am Wochenende: Torten und traditionelle Kuchen backen lernen mit Meisterbäcker Klaus."
                    },
                    "ad_b": {
                        "title": "www.kochschule-wurst.de",
                        "text_de": "Grill- und Fleischkochkurse: Steaks und Bratwürste perfekt zubereiten. Freitagabend."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是甜品烘焙班（Backkurse Torten backen），B 是烤肉香肠烹饪班，选 A。"
                },
                {
                    "id": "a1_l_03_t2_q08",
                    "teil": 2,
                    "user_need_zh": "您想租一套靠近大学的单身公寓。",
                    "ad_a": {
                        "title": "www.studentenwohnung-uni.de",
                        "text_de": "1-Zimmer-Appartements direkt am Uni-Campus. Voll möbliert mit Internet ab 380 € warm."
                    },
                    "ad_b": {
                        "title": "www.luxus-villa-see.de",
                        "text_de": "Exklusives Einfamilienhaus mit 6 Zimmern und Pool auf dem Land. 2500 € Kaltmiete."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是大学旁边的单人学生公寓（1-Zimmer-Appartements am Uni-Campus），B 是郊区豪宅，选 A。"
                },
                {
                    "id": "a1_l_03_t2_q09",
                    "teil": 2,
                    "user_need_zh": "您需要找人给家里打扫卫生和擦窗户。",
                    "ad_a": {
                        "title": "www.putzfee-reinigung.de",
                        "text_de": "Zuverlässige Haushaltshilfe: Wohnungsreinigung, Fensterputzen und Bügelservice nach Stundenabrechnung."
                    },
                    "ad_b": {
                        "title": "www.gaertner-profi.de",
                        "text_de": "Gartenpflege und Baumschnitt: Rasenmähen, Hecken schneiden und Unkraut jäten."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 提供家庭保洁和擦窗服务（Wohnungsreinigung, Fensterputzen），B 是园艺修树，选 A。"
                },
                {
                    "id": "a1_l_03_t2_q10",
                    "teil": 2,
                    "user_need_zh": "您想在市中心找一家可以免费无线上网的安静咖啡馆。",
                    "ad_a": {
                        "title": "www.disco-club-night.de",
                        "text_de": "Party bis zum Morgen! DJ-Musik und Cocktails ab 22:00 Uhr. Eintritt 10 Euro."
                    },
                    "ad_b": {
                        "title": "www.cafe-leselust.de",
                        "text_de": "Ruhiges Café im Zentrum: Frischer Kaffee, hausgemachter Kuchen, kostenloses Highspeed-WLAN und Buchausleihe."
                    },
                    "answer_key": "B",
                    "explanation_zh": "B 是带免费 WLAN 的安静阅读咖啡馆（Ruhiges Café mit WLAN），A 是夜店酒吧，选 B。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_l_03_t3_q11",
                    "teil": 3,
                    "sign_text_de": "Gepäckaufbewahrung im Untergeschoss! Geöffnet täglich von 6:00 bis 23:00 Uhr.",
                    "statement_de": "Man kann seine Koffer hier auch am Abend abgeben.",
                    "statement_zh": "晚上也可以在这里寄存行李箱。",
                    "answer_key": "R",
                    "explanation_zh": "营业至晚上 23 点（bis 23:00 Uhr），晚上可以寄存，选 R。"
                },
                {
                    "id": "a1_l_03_t3_q12",
                    "teil": 3,
                    "sign_text_de": "Achtung Hochspannung! Lebensgefahr! Betreten streng verboten!",
                    "statement_de": "Der Zutritt ist hier für jedermann erlaubt.",
                    "statement_zh": "任何人都允许进入这里。",
                    "answer_key": "F",
                    "explanation_zh": "标牌警告高压危险严禁入内（'Betreten streng verboten'），选 F。"
                },
                {
                    "id": "a1_l_03_t3_q13",
                    "teil": 3,
                    "sign_text_de": "Fahrradständer: Das Anschließen von Motorrädern ist untersagt.",
                    "statement_de": "Motorräder dürfen hier nicht abgestellt werden.",
                    "statement_zh": "摩托车不允许停放在这里。",
                    "answer_key": "R",
                    "explanation_zh": "标牌写明禁止锁摩托车（'ist untersagt' = 禁止），选 R。"
                },
                {
                    "id": "a1_l_03_t3_q14",
                    "teil": 3,
                    "sign_text_de": "Bürgerbüro: Bitte ziehen Sie am Automaten eine Wartenummer.",
                    "statement_de": "Man kann ohne Wartenummer direkt zum Schalter gehen.",
                    "statement_zh": "不用取号可以直接去柜台办理。",
                    "answer_key": "F",
                    "explanation_zh": "必须在取号机取号（'Bitte ziehen Sie ... eine Wartenummer'），选 F。"
                },
                {
                    "id": "a1_l_03_t3_q15",
                    "teil": 3,
                    "sign_text_de": "Im Brandfall Aufzüge nicht benutzen! Treppenhaus verwenden!",
                    "statement_de": "Wenn es brennt, soll man die Treppe nehmen.",
                    "statement_zh": "发生火灾时应该走楼梯。",
                    "answer_key": "R",
                    "explanation_zh": "火灾发生严禁乘电梯，走楼梯（'Treppenhaus verwenden'），选 R。"
                }
            ]
        }
    },

    # ── SET 04 ──────────────────────────────────────────────────────────────
    {
        "set_id": 4,
        "title_de": "Goethe-Zertifikat A1 Lesen Modellsatz 04",
        "title_zh": "歌德 A1 官方阅读全真卷 04",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_l_04_t1_q01",
                    "teil": 1,
                    "reading_text_de": "Liebe Sandra, wir machen am Sonntag ein Picknick im Stadtpark. Jeder bringt etwas zu essen mit. Ich backe Muffins. Kannst du Saft und Mineralwasser besorgen? Treffpunkt 14 Uhr am Brunnen. LG Paul",
                    "statement_de": "Das Picknick findet am Sonntag statt.",
                    "statement_zh": "野餐在周日举行。",
                    "answer_key": "R",
                    "explanation_zh": "Paul 写明 'am Sonntag ein Picknick'，选 R。"
                },
                {
                    "id": "a1_l_04_t1_q02",
                    "teil": 1,
                    "reading_text_de": "Liebe Sandra, wir machen am Sonntag ein Picknick im Stadtpark. Jeder bringt etwas zu essen mit. Ich backe Muffins. Kannst du Saft und Mineralwasser besorgen? Treffpunkt 14 Uhr am Brunnen. LG Paul",
                    "statement_de": "Paul bittet Sandra, Getränke mitzubringen.",
                    "statement_zh": "保罗请求桑德拉带饮料。",
                    "answer_key": "R",
                    "explanation_zh": "Paul 请求 'Kannst du Saft und Mineralwasser besorgen?'，选 R。"
                },
                {
                    "id": "a1_l_04_t1_q03",
                    "teil": 1,
                    "reading_text_de": "Sehr geehrte Mieter, wegen Reinigungsarbeiten bleibt die Tiefgarage am Dienstag von 8 bis 14 Uhr gesperrt. Bitte parken Sie Ihre Fahrzeuge rechtzeitig draußen. Hausverwaltung",
                    "statement_de": "Am Dienstag kann man nicht in der Tiefgarage parken.",
                    "statement_zh": "周二不能在地下车库停车。",
                    "answer_key": "R",
                    "explanation_zh": "通知明确周二 8-14 点封锁（'bleibt ... gesperrt'），选 R。"
                },
                {
                    "id": "a1_l_04_t1_q04",
                    "teil": 1,
                    "reading_text_de": "Sehr geehrte Mieter, wegen Reinigungsarbeiten bleibt die Tiefgarage am Dienstag von 8 bis 14 Uhr gesperrt. Bitte parken Sie Ihre Fahrzeuge rechtzeitig draußen. Hausverwaltung",
                    "statement_de": "Die Garage wird am Wochenende gereinigt.",
                    "statement_zh": "车库在周末进行清洁。",
                    "answer_key": "F",
                    "explanation_zh": "是在周二（am Dienstag）而非周末，选 F。"
                },
                {
                    "id": "a1_l_04_t1_q05",
                    "teil": 1,
                    "reading_text_de": "Hallo David, ich schaffe es heute leider nicht pünktlich zum Sport. Mein Zug hat 30 Minuten Verspätung. Fangt schon ohne mich an! Gruß Martin",
                    "statement_de": "Martin kommt pünktlich zum Sport.",
                    "statement_zh": "马丁准时去参加体育运动。",
                    "answer_key": "F",
                    "explanation_zh": "Martin 火车晚点无法准时（'schaffe es heute leider nicht pünktlich'），选 F。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_l_04_t2_q06",
                    "teil": 2,
                    "user_need_zh": "您想买一双舒适的登山鞋去阿尔卑斯山徒步。",
                    "ad_a": {
                        "title": "www.outdoor-alpin-shop.de",
                        "text_de": "Große Auswahl an Wanderschuhen, Trekkingschuhen und Rucksäcken. Professionelle Beratung für Bergsportler."
                    },
                    "ad_b": {
                        "title": "www.elegante-damenschuhe.de",
                        "text_de": "Exklusive High-Heels, Abendschuhe und Pumps für festliche Anlässe und Hochzeiten."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是专业的户外登山鞋店（Wanderschuhen, Trekkingschuhen），B 是宴会高跟鞋店，选 A。"
                },
                {
                    "id": "a1_l_04_t2_q07",
                    "teil": 2,
                    "user_need_zh": "您想让孩子在假期学习游泳拿到海马标（Seepferdchen）。",
                    "ad_a": {
                        "title": "www.schwimmschule-delfin.de",
                        "text_de": "Schwimmkurse für Kinder ab 5 Jahren: Intensivkurse in den Ferien mit Seepferdchen-Prüfung."
                    },
                    "ad_b": {
                        "title": "www.tauchschule-ozean.de",
                        "text_de": "Gerätetauchen für Erwachsene im See. Mindestalter 18 Jahre. Internationaler Tauchschein."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是儿童假期游泳海马班（Schwimmkurse für Kinder Seepferdchen），B 是成人潜水课，选 A。"
                },
                {
                    "id": "a1_l_04_t2_q08",
                    "teil": 2,
                    "user_need_zh": "您想找一家提供全天24小时送货服务的药店。",
                    "ad_a": {
                        "title": "www.city-apotheke-express.de",
                        "text_de": "24h-Notdienst und schneller Lieferservice für Medikamente direkt an Ihre Haustür."
                    },
                    "ad_b": {
                        "title": "www.reformhaus-bio.de",
                        "text_de": "Biologische Lebensmittel, Tees und Naturkosmetik. Geöffnet Mo-Fr 9-18 Uhr. Keine Arzneimittel."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 提供 24 小时药品配送（24h-Notdienst Lieferservice Medikamente），B 是健康食品店且无药品，选 A。"
                },
                {
                    "id": "a1_l_04_t2_q09",
                    "teil": 2,
                    "user_need_zh": "您想预订一张去汉堡的廉价长途大巴车票。",
                    "ad_a": {
                        "title": "www.fernreise-bus.de",
                        "text_de": "Günstig mit dem Fernbus reisen: Täglich direkte Verbindungen nach Hamburg ab 9,99 Euro mit WLAN und Steckdosen."
                    },
                    "ad_b": {
                        "title": "www.fluggesellschaft-aero.de",
                        "text_de": "Internationale Flugreisen weltweit. Flüge nach Amerika und Asien buchen."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是去汉堡的廉价长途大巴（Fernbus nach Hamburg ab 9,99 Euro），B 是国际航班，选 A。"
                },
                {
                    "id": "a1_l_04_t2_q10",
                    "teil": 2,
                    "user_need_zh": "您想在周末参观当代现代艺术展览。",
                    "ad_a": {
                        "title": "www.museum-moderne-kunst.de",
                        "text_de": "Museum für Moderne Kunst: Sonderausstellung Gegenwartsmalerei. Sa & So 10 bis 19 Uhr geöffnet."
                    },
                    "ad_b": {
                        "title": "www.technik-museum-alt.de",
                        "text_de": "Historische Dampflokomotiven und Flugzeuge aus den 1920er Jahren. Technikgeschichte."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是现代艺术博物馆（Museum für Moderne Kunst），B 是老蒸汽机车技术馆，选 A。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_l_04_t3_q11",
                    "teil": 3,
                    "sign_text_de": "Kein Trinkwasser! Dieses Wasser ist nicht zum Trinken geeignet.",
                    "statement_de": "Man darf dieses Wasser gefahrlos trinken.",
                    "statement_zh": "可以安全饮用这里的自来水。",
                    "answer_key": "F",
                    "explanation_zh": "标牌注明非饮用水（'Kein Trinkwasser'），陈述说可以安全饮用，错误，选 F。"
                },
                {
                    "id": "a1_l_04_t3_q12",
                    "teil": 3,
                    "sign_text_de": "Museums-Shop: Fotografieren im Verkaufsraum verboten!",
                    "statement_de": "Man darf im Shop keine Fotos machen.",
                    "statement_zh": "在商店内严禁拍照。",
                    "answer_key": "R",
                    "explanation_zh": "标牌注明禁止拍照（'Fotografieren ... verboten'），选 R。"
                },
                {
                    "id": "a1_l_04_t3_q13",
                    "teil": 3,
                    "sign_text_de": "Bitte die Treppe sauber halten! Müll in die Behälter werfen.",
                    "statement_de": "Abfall soll in die Mülleimer geworfen werden.",
                    "statement_zh": "垃圾应当扔进垃圾箱中。",
                    "answer_key": "R",
                    "explanation_zh": "标牌明确要求扔进垃圾箱（'Müll in die Behälter werfen'），选 R。"
                },
                {
                    "id": "a1_l_04_t3_q14",
                    "teil": 3,
                    "sign_text_de": "Schwimmbecken: Nur für Schwimmer! Wassertiefe 2,50 Meter.",
                    "statement_de": "Auch Nichtschwimmer dürfen in dieses Becken gehen.",
                    "statement_zh": "不会游泳的人也可以进入这个深水池。",
                    "answer_key": "F",
                    "explanation_zh": "仅限会游泳者且水深 2.5 米（'Nur für Schwimmer'），陈述错误，选 F。"
                },
                {
                    "id": "a1_l_04_t3_q15",
                    "teil": 3,
                    "sign_text_de": "Sitzplatz reserviert für ältere Menschen und Schwangere.",
                    "statement_de": "Dieser Platz ist besonders für Senioren und werdende Mütter gedacht.",
                    "statement_zh": "该座位专供老年人与孕妇优先使用。",
                    "answer_key": "R",
                    "explanation_zh": "标牌注明专供长者和孕妇使用，选 R。"
                }
            ]
        }
    },

    # ── SET 05 ──────────────────────────────────────────────────────────────
    {
        "set_id": 5,
        "title_de": "Goethe-Zertifikat A1 Lesen Modellsatz 05",
        "title_zh": "歌德 A1 官方阅读全真卷 05",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_l_05_t1_q01",
                    "teil": 1,
                    "reading_text_de": "Liebe Frau Schneider, vielen Dank für das freundliche Telefonat. Ich bestätige hiermit unseren Termin zum Vorstellungsgespräch am Donnerstag um 10:30 Uhr. Mit besten Grüßen, Claudia Bauer",
                    "statement_de": "Claudia Bauer hat am Donnerstag ein Bewerbungsgespräch.",
                    "statement_zh": "克劳迪娅·鲍尔周四有一场面试。",
                    "answer_key": "R",
                    "explanation_zh": "信中确认面试约会（'Termin zum Vorstellungsgespräch am Donnerstag'），选 R。"
                },
                {
                    "id": "a1_l_05_t1_q02",
                    "teil": 1,
                    "reading_text_de": "Liebe Frau Schneider, vielen Dank für das freundliche Telefonat. Ich bestätige hiermit unseren Termin zum Vorstellungsgespräch am Donnerstag um 10:30 Uhr. Mit besten Grüßen, Claudia Bauer",
                    "statement_de": "Der Termin ist am Freitagnachmittag.",
                    "statement_zh": "约会是在周五下午。",
                    "answer_key": "F",
                    "explanation_zh": "是在周四上午 10:30（am Donnerstag um 10:30），选 F。"
                },
                {
                    "id": "a1_l_05_t1_q03",
                    "teil": 1,
                    "reading_text_de": "Hallo Max, ich habe unsere Kinokarten für heute Abend online gekauft. Der Film fängt um 20:15 Uhr an. Treffen wir uns um 19:45 Uhr im Foyer? Gruß Felix",
                    "statement_de": "Felix hat die Kinokarten bereits bezahlt.",
                    "statement_zh": "菲利克斯已经买好了电影票。",
                    "answer_key": "R",
                    "explanation_zh": "Felix 确认已在线买好（'online gekauft'），选 R。"
                },
                {
                    "id": "a1_l_05_t1_q04",
                    "teil": 1,
                    "reading_text_de": "Hallo Max, ich habe unsere Kinokarten für heute Abend online gekauft. Der Film fängt um 20:15 Uhr an. Treffen wir uns um 19:45 Uhr im Foyer? Gruß Felix",
                    "statement_de": "Der Film beginnt um 19:45 Uhr.",
                    "statement_zh": "电影在19:45开始放映。",
                    "answer_key": "F",
                    "explanation_zh": "放映是在 20:15（19:45 是碰头时间），选 F。"
                },
                {
                    "id": "a1_l_05_t1_q05",
                    "teil": 1,
                    "reading_text_de": "Liebe Nachbarn, wegen einer Familienfeier kann es am Samstagabend ab 20 Uhr etwas lauter werden. Wir bitten um Ihr Verständnis. Familie Weber, 2. Stock",
                    "statement_de": "Familie Weber feiert am Samstagabend ein Fest.",
                    "statement_zh": "韦伯一家周六晚上举办聚会。",
                    "answer_key": "R",
                    "explanation_zh": "通知说明有家庭聚会（'Familienfeier ... am Samstagabend'），选 R。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_l_05_t2_q06",
                    "teil": 2,
                    "user_need_zh": "您想在周末租一艘小划艇去河上划船。",
                    "ad_a": {
                        "title": "www.bootsverleih-flusspark.de",
                        "text_de": "Kanu- und Tretbootverleih an der Ruhr. Täglich ab 10 Uhr. Schwimmwesten für Kinder kostenlos."
                    },
                    "ad_b": {
                        "title": "www.skischule-schnee.de",
                        "text_de": "Skikurse und Snowboardunterricht in den Wintermonaten. Verleih von Skiausrüstung."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是小船租赁（Kanu- und Tretbootverleih），B 是滑雪学校，选 A。"
                },
                {
                    "id": "a1_l_05_t2_q07",
                    "teil": 2,
                    "user_need_zh": "您想买一台二手的苹果笔记本电脑。",
                    "ad_a": {
                        "title": "www.gebraucht-it-markt.de",
                        "text_de": "Geprüfte gebrauchte Laptops, MacBooks und Tablets mit 1 Jahr Garantie. Günstige Preise."
                    },
                    "ad_b": {
                        "title": "www.antiquitaeten-galerie.de",
                        "text_de": "Alte Ölgemälde, Skulpturen und Vintage-Schmuck. Kunsthandel seit 1950."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 售卖二手 MacBook 笔记本（Gebrauchte Laptops, MacBooks），B 是古董画廊，选 A。"
                },
                {
                    "id": "a1_l_05_t2_q08",
                    "teil": 2,
                    "user_need_zh": "您想在周末参加一次市中心的德语导游徒步观光。",
                    "ad_a": {
                        "title": "www.stadtfuehrung-historisch.de",
                        "text_de": "Historische Stadtrundgänge zu Fuß mit qualifizierten Stadtführern. Samstag & Sonntag 11:00 Uhr ab Rathaus."
                    },
                    "ad_b": {
                        "title": "www.autovermietung-flott.de",
                        "text_de": "Mietwagen für Geschäfts- und Urlaubsreisen. Abholung am Hauptbahnhof oder Flughafen."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是周末徒步城市导览（Stadtrundgänge zu Fuß Samstag & Sonntag），B 是租车公司，选 A。"
                },
                {
                    "id": "a1_l_05_t2_q09",
                    "teil": 2,
                    "user_need_zh": "您想为您的孩子找一位负责任的德语一对一家教老师。",
                    "ad_a": {
                        "title": "www.nachhilfe-profi-deutsch.de",
                        "text_de": "Individuelle Deutsch-Nachhilfe für Schüler aller Klassen. Grammatik, Rechtschreibung und Leseförderung."
                    },
                    "ad_b": {
                        "title": "www.tanzschule-rhythmus.de",
                        "text_de": "Tanzkurse für Paare und Singles: Salsa, Walzer und Tango. Keine schulische Nachhilfe."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是一对一德语课外辅导（Deutsch-Nachhilfe für Schüler），B 是交谊舞学校，选 A。"
                },
                {
                    "id": "a1_l_05_t2_q10",
                    "teil": 2,
                    "user_need_zh": "您想买一张去维也纳的廉价机票。",
                    "ad_a": {
                        "title": "www.flug-suche-direkt.de",
                        "text_de": "Flugpreisvergleich: Billigflüge nach Wien ab 29 Euro. Täglich mehrere Direktflüge verfügbar."
                    },
                    "ad_b": {
                        "title": "www.hotel-wien-zentrum.de",
                        "text_de": "Zimmervermittlung für Hotels und Pensionen in Wien. Keine Flugbuchung."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是维也纳机票比价预订（Billigflüge nach Wien ab 29 Euro），B 仅订酒店无机票，选 A。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_l_05_t3_q11",
                    "teil": 3,
                    "sign_text_de": "Zugang nur für Mitarbeiter mit Ausweis! Besucher bitte am Empfang melden.",
                    "statement_de": "Besucher dürfen ohne Anmeldung eintreten.",
                    "statement_zh": "访客可以不经登记直接进入。",
                    "answer_key": "F",
                    "explanation_zh": "标牌要求访客必须在前台登记（'Besucher bitte am Empfang melden'），选 F。"
                },
                {
                    "id": "a1_l_05_t3_q12",
                    "teil": 3,
                    "sign_text_de": "Keine EC-Kartenzahlung unter 10 Euro möglich.",
                    "statement_de": "Wenn Sie für 5 Euro einkaufen, müssen Sie bar bezahlen.",
                    "statement_zh": "如果您消费 5 欧元，必须现金支付。",
                    "answer_key": "R",
                    "explanation_zh": "标牌说明 10 欧以下无法刷卡，5 欧必须付现金，选 R。"
                },
                {
                    "id": "a1_l_05_t3_q13",
                    "teil": 3,
                    "sign_text_de": "Parkhaus: Höhenbegrenzung maximal 2,00 Meter.",
                    "statement_de": "Ein Fahrzeug mit 2,30 Meter Höhe darf hier einfahren.",
                    "statement_zh": "高度为 2.30 米的车辆允许驶入该停车楼。",
                    "answer_key": "F",
                    "explanation_zh": "限高 2.00 米（'maximal 2,00 Meter'），2.30 米超高不允许进入，选 F。"
                },
                {
                    "id": "a1_l_05_t3_q14",
                    "teil": 3,
                    "sign_text_de": "Gartenanlage: Hunde sind an der kurzen Leine zu führen.",
                    "statement_de": "Hunde dürfen hier frei ohne Leine herumlaufen.",
                    "statement_zh": "狗可以在这里不拴绳自由奔跑。",
                    "answer_key": "F",
                    "explanation_zh": "标牌要求必须拴短绳（'an der kurzen Leine zu führen'），选 F。"
                },
                {
                    "id": "a1_l_05_t3_q15",
                    "teil": 3,
                    "sign_text_de": "Fahrradwerkstatt: Samstags nur Abholung von reparierten Rädern, keine Neuannahme.",
                    "statement_de": "Man kann am Samstag sein kaputtes Fahrrad zur Reparatur bringen.",
                    "statement_zh": "可以在周六送坏了的自行车去修理。",
                    "answer_key": "F",
                    "explanation_zh": "标牌强调周六仅供取车不接受新维修（'keine Neuannahme'），选 F。"
                }
            ]
        }
    },

    # ── SET 06 ──────────────────────────────────────────────────────────────
    {
        "set_id": 6,
        "title_de": "Goethe-Zertifikat A1 Lesen Modellsatz 06",
        "title_zh": "歌德 A1 官方阅读全真卷 06",
        "total_questions": 15,
        "parts": {
            "teil_1": [
                {
                    "id": "a1_l_06_t1_q01",
                    "teil": 1,
                    "reading_text_de": "Lieber Herr Berger, vielen Dank für das freundliche Gespräch. Die Schlüssel für die Ferienwohnung liegen ab Freitag 14 Uhr im Schlüsseltresor neben der Haustür bereit. Der Code lautet 4821. Sonnige Grüße, Familie Sommer",
                    "statement_de": "Herr Berger kann ab Freitag in die Ferienwohnung.",
                    "statement_zh": "伯格先生周五起可以入住度假屋。",
                    "answer_key": "R",
                    "explanation_zh": "信中交待周五 14 点起钥匙在密码盒就绪（'ab Freitag 14 Uhr ... bereit'），选 R。"
                },
                {
                    "id": "a1_l_06_t1_q02",
                    "teil": 1,
                    "reading_text_de": "Lieber Herr Berger, vielen Dank für das freundliche Gespräch. Die Schlüssel für die Ferienwohnung liegen ab Freitag 14 Uhr im Schlüsseltresor neben der Haustür bereit. Der Code lautet 4821. Sonnige Grüße, Familie Sommer",
                    "statement_de": "Familie Sommer übergibt die Schlüssel persönlich an der Tür.",
                    "statement_zh": "萨默一家在门口亲自当面交接钥匙。",
                    "answer_key": "F",
                    "explanation_zh": "钥匙放在密码盒（Schlüsseltresor）通过密码自取，并非当面交付，选 F。"
                },
                {
                    "id": "a1_l_06_t1_q03",
                    "teil": 1,
                    "reading_text_de": "Liebe Lena, mein Drucker ist leider kaputt. Kannst du bitte mein Flugticket für morgen ausdrucken und heute Abend mitbringen? Tausend Dank! Bussi, Mia",
                    "statement_de": "Mia braucht Hilfe beim Drucken des Flugtickets.",
                    "statement_zh": "米娅在打印机票上需要帮助。",
                    "answer_key": "R",
                    "explanation_zh": "Mia 打印机坏了请求对方代为打印，选 R。"
                },
                {
                    "id": "a1_l_06_t1_q04",
                    "teil": 1,
                    "reading_text_de": "Liebe Lena, mein Drucker ist leider kaputt. Kannst du bitte mein Flugticket für morgen ausdrucken und heute Abend mitbringen? Tausend Dank! Bussi, Mia",
                    "statement_de": "Mias Drucker funktioniert einwandfrei.",
                    "statement_zh": "米娅的打印机运转良好毫无问题。",
                    "answer_key": "F",
                    "explanation_zh": "信中说明打印机坏了（'Drucker ist leider kaputt'），选 F。"
                },
                {
                    "id": "a1_l_06_t1_q05",
                    "teil": 1,
                    "reading_text_de": "Liebe Kursteilnehmer, wegen einer Fortbildung der Lehrkräfte fällt der Deutschunterricht am Mittwoch aus. Der nächste Unterricht findet regulär am Freitag statt. Sprachschule Mitte",
                    "statement_de": "Am Mittwoch gibt es keinen Deutschunterricht.",
                    "statement_zh": "周三没有德语课。",
                    "answer_key": "R",
                    "explanation_zh": "通知写明周三停课（'am Mittwoch aus'），选 R。"
                }
            ],
            "teil_2": [
                {
                    "id": "a1_l_06_t2_q06",
                    "teil": 2,
                    "user_need_zh": "您想在周末租一辆大货车来搬家搬运家具。",
                    "ad_a": {
                        "title": "www.transporter-mieten-24.de",
                        "text_de": "Transporter und LKW für Ihren Umzug: Große Ladefläche ab 49 € pro Tag. Auch am Wochenende günstig mieten."
                    },
                    "ad_b": {
                        "title": "www.cabrio-cruiser.de",
                        "text_de": "Sportliche Cabrios für Wochenendausflüge. 2 Sitze, luxuriöse Ausstattung. Keine Lastenfahrzeuge."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是搬家货车租赁（Transporter und LKW für Umzug），B 是双门敞篷跑车，选 A。"
                },
                {
                    "id": "a1_l_06_t2_q07",
                    "teil": 2,
                    "user_need_zh": "您想买一把适合初学者的古典木吉他。",
                    "ad_a": {
                        "title": "www.musikhaus-akkord.de",
                        "text_de": "Akustische Gitarren für Anfänger und Fortgeschrittene inklusive Tasche und Stimmgerät ab 79 Euro."
                    },
                    "ad_b": {
                        "title": "www.klavier-meister.de",
                        "text_de": "Klavier- und Flügelverkauf. Stimmung und Transport von Flügeln. Keine Zupfinstrumente."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是吉他乐器店（Akustische Gitarren für Anfänger），B 是钢琴专卖店，选 A。"
                },
                {
                    "id": "a1_l_06_t2_q08",
                    "teil": 2,
                    "user_need_zh": "您想在周五晚上吃地道美味的西班牙海鲜饭（Paella）。",
                    "ad_a": {
                        "title": "www.tapas-bar-espana.de",
                        "text_de": "Spanische Tapas, frische Paella und Sangria. Freitags Live-Gitarrenmusik ab 19:00 Uhr."
                    },
                    "ad_b": {
                        "title": "www.sushi-bar-tokyo.de",
                        "text_de": "Japanische Sushi-Spezialitäten, Sashimi und Miso-Suppe. Lieferservice und Restaurant."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是正宗西班牙海鲜饭 Tapas 餐厅（Spanische Tapas, frische Paella），B 是日料寿司店，选 A。"
                },
                {
                    "id": "a1_l_06_t2_q09",
                    "teil": 2,
                    "user_need_zh": "您想找一家提供 1 小时内快速洗印照片的照相馆。",
                    "ad_a": {
                        "title": "www.foto-express-studio.de",
                        "text_de": "Passbilder und Fotodruck sofort zum Mitnehmen innerhalb von 15 Minuten. Digitaler Fotoservice."
                    },
                    "ad_b": {
                        "title": "www.malerei-atelier-farbkunst.de",
                        "text_de": "Ölgemälde und Porträtzeichnungen von Hand gemalt. Anfertigungsdauer 2-4 Wochen."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 提供 15 分钟立等可取的照片冲印（Fotodruck sofort zum Mitnehmen 15 min），B 是手工油画作坊（需2-4周），选 A。"
                },
                {
                    "id": "a1_l_06_t2_q10",
                    "teil": 2,
                    "user_need_zh": "您想给您的公寓换一把新的防盗安全门锁。",
                    "ad_a": {
                        "title": "www.schluesseldienst-sicherheit.de",
                        "text_de": "Schlüsseldienst & Sicherheitstechnik: Montage von Sicherheitsschlössern, Türöffnung und Einbruchschutz rund um die Uhr."
                    },
                    "ad_b": {
                        "title": "www.fensterbau-glas.de",
                        "text_de": "Herstellung von Isolierglasfenstern und Wintergärten. Keine Schlosserei."
                    },
                    "answer_key": "A",
                    "explanation_zh": "A 是专业配锁与安全锁装配（Montage von Sicherheitsschlössern），B 是玻璃窗制作，选 A。"
                }
            ],
            "teil_3": [
                {
                    "id": "a1_l_06_t3_q11",
                    "teil": 3,
                    "sign_text_de": "Fahrkartenentwerter: Fahrscheine bitte vor Fahrtantritt hier entwerten!",
                    "statement_de": "Man muss die Fahrkarte vor dem Einsteigen abstempeln.",
                    "statement_zh": "上车前必须将车票打票生效。",
                    "answer_key": "R",
                    "explanation_zh": "标牌要求上车前打票（'vor Fahrtantritt ... entwerten'），选 R。"
                },
                {
                    "id": "a1_l_06_t3_q12",
                    "teil": 3,
                    "sign_text_de": "Privatgrundstück! Unbefugtes Betreten verboten! Zuwiderhandlungen werden angezeigt.",
                    "statement_de": "Fremde Personen dürfen dieses Grundstück jederzeit betreten.",
                    "statement_zh": "外人随时可以进入这块私有地产。",
                    "answer_key": "F",
                    "explanation_zh": "标牌严禁非授权人员进入（'Unbefugtes Betreten verboten'），选 F。"
                },
                {
                    "id": "a1_l_06_t3_q13",
                    "teil": 3,
                    "sign_text_de": "Supermarkt: Wegen Inventur heute ab 16 Uhr geschlossen.",
                    "statement_de": "Der Supermarkt hat heute bis 20 Uhr geöffnet.",
                    "statement_zh": "超市今天营业至晚上20点。",
                    "answer_key": "F",
                    "explanation_zh": "因盘点今天 16 点起关门（'ab 16 Uhr geschlossen'），陈述说营业至20点，错误，选 F。"
                },
                {
                    "id": "a1_l_06_t3_q14",
                    "teil": 3,
                    "sign_text_de": "Tierpark: Füttern der Tiere strengstens verboten! Bitte Müll trennen.",
                    "statement_de": "Besucher dürfen den Tieren eigenes Futter geben.",
                    "statement_zh": "游客可以给动物喂自己带的饲料。",
                    "answer_key": "F",
                    "explanation_zh": "标牌注明严禁给动物喂食（'Füttern der Tiere strengstens verboten'），选 F。"
                },
                {
                    "id": "a1_l_06_t3_q15",
                    "teil": 3,
                    "sign_text_de": "Parkhaus: Kassenautomat befindet sich am Hauptausgang im Erdgeschoss.",
                    "statement_de": "Hier kann man direkt an der Schranke bar bezahlen.",
                    "statement_zh": "可以在车库出口闸机处直接付现金。",
                    "answer_key": "F",
                    "explanation_zh": "自动缴费机在底层主出口处（im Erdgeschoss），并非在道闸处，选 F。"
                }
            ]
        }
    }
]

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

def get_lesen_set_list() -> List[Dict[str, Any]]:
    """返回 6 套 A1 阅读试卷概览列表"""
    return [
        {
            "set_id": s["set_id"],
            "title_de": s["title_de"],
            "title_zh": s["title_zh"],
            "total_questions": s["total_questions"]
        }
        for s in A1_LESEN_SETS
    ]


def get_lesen_set_by_id(set_id: int, sanitize: bool = True) -> Optional[Dict[str, Any]]:
    """获取指定套题内容。sanitize=True 时剔除答案与解析"""
    target = None
    for s in A1_LESEN_SETS:
        if s["set_id"] == set_id:
            target = s
            break
    if not target:
        return None

    if not sanitize:
        return target

    sanitized_parts = {}
    for part_name, questions in target["parts"].items():
        clean_questions = []
        for q in questions:
            clean_q = dict(q)
            clean_q.pop("answer_key", None)
            clean_q.pop("explanation_zh", None)
            clean_questions.append(clean_q)
        sanitized_parts[part_name] = clean_questions

    return {
        "set_id": target["set_id"],
        "title_de": target["title_de"],
        "title_zh": target["title_zh"],
        "total_questions": target["total_questions"],
        "parts": sanitized_parts
    }


def grade_lesen_answers(set_id: int, user_answers: Dict[str, str]) -> Dict[str, Any]:
    """
    批改 A1 阅读答题，计算 25 分制官方得分与评定等级：
    20.0 ~ 25.0: Sehr gut
    17.5 ~ 19.9: Gut
    15.0 ~ 17.4: Befriedigend
    12.5 ~ 14.9: Ausreichend
    < 12.5:      Nicht bestanden
    """
    raw_set = get_lesen_set_by_id(set_id, sanitize=False)
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
                "explanation_zh": q["explanation_zh"]
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
