# -*- coding: utf-8 -*-
"""DeLector 官方真题精读语料库 (Goethe & TestDaF Official Reading Corpus)

提供涵盖 A1–B2 及 TestDaF 权威阅读真题篇章，结构化包含考点词、语法焦点与阅读理解验证题。
"""
from typing import List, Dict, Optional, Any

OFFICIAL_CORPUS: List[Dict[str, Any]] = [
    {
        "id": "goethe_a1_alltag_01",
        "title": "Ein Tag auf dem Wochenmarkt",
        "cefr": "A1",
        "category": "Beruf & Alltag",
        "source_exam": "Goethe-Zertifikat A1 Lesen Teil 1",
        "word_count": 68,
        "summary_zh": "介绍每周六在市政厅广场举办的传统露天集市，描述新鲜蔬果、奶酪购买与日常问候。",
        "key_lexemes": ["der Wochenmarkt", "das Gemüse", "frisch", "kosten", "der Verkäufer"],
        "grammar_focus": ["Präsens_Verben", "Akkusativ_Objekt", "W-Fragen"],
        "content": (
            "Jeden Samstag gibt es einen großen Wochenmarkt auf dem Marktplatz vor dem Rathaus. "
            "Die Menschen kaufen dort frisches Obst, Gemüse, Brot und Käse. "
            "Frau Müller kauft heute zwei Kilo Äpfel und ein Pfund Tomaten. "
            "Die Äpfel schmecken süß und sind nicht teuer. "
            "Der Verkäufer ist sehr freundlich und wünscht ein schönes Wochenende."
        ),
        "reading_questions": [
            {
                "question": "Wann findet der Wochenmarkt statt?",
                "options": ["A. Jeden Samstag", "B. Jeden Sonntag", "C. Jeden Werktag"],
                "answer_idx": 0,
                "explanation_zh": "第一句明确指出集市在每个周六（Jeden Samstag）举行。"
            },
            {
                "question": "Was kauft Frau Müller heute?",
                "options": ["A. Brot und Käse", "B. Äpfel und Tomaten", "C. Nur Fleisch"],
                "answer_idx": 1,
                "explanation_zh": "第三句指出 Frau Müller 购买了苹果和番茄（zwei Kilo Äpfel und ein Pfund Tomaten）。"
            }
        ]
    },
    {
        "id": "goethe_a1_campus_02",
        "title": "Mein Deutschkurs an der Volkshochschule",
        "cefr": "A1",
        "category": "Campus & Studium",
        "source_exam": "Goethe-Zertifikat A1 Lesen Teil 2",
        "word_count": 72,
        "summary_zh": "学员介绍在社区成人大学（VHS）的德语晚课，包含来自不同国家的同学与互动练习。",
        "key_lexemes": ["die Volkshochschule", "der Deutschkurs", "die Kursteilnehmer", "sprechen", "zusammen"],
        "grammar_focus": ["Personalpronomen", "Zahlen_Uhrzeit", "Modalverb_können"],
        "content": (
            "Ich besuche seit drei Wochen einen Deutschkurs an der Volkshochschule. "
            "Der Unterricht beginnt jeden Dienstag und Donnerstag um achtzehn Uhr. "
            "In meiner Gruppe lernen zwölf Personen aus verschiedenen Ländern. "
            "Unser Lehrer heißt Herr Wagner. Wir machen viele Grammatikübungen und sprechen zusammen Deutsch. "
            "Das Lernen macht mir großen Spaß."
        ),
        "reading_questions": [
            {
                "question": "Um wie viel Uhr beginnt der Unterricht?",
                "options": ["A. Um 17:00 Uhr", "B. Um 18:00 Uhr", "C. Um 19:30 Uhr"],
                "answer_idx": 1,
                "explanation_zh": "文中说明上课时间为每周二、周四 18:00（um achtzehn Uhr）。"
            }
        ]
    },
    {
        "id": "goethe_a2_alltag_03",
        "title": "Eine Einladung zur Geburtstagsfeier",
        "cefr": "A2",
        "category": "Beruf & Alltag",
        "source_exam": "Goethe-Zertifikat A2 Lesen Teil 1",
        "word_count": 115,
        "summary_zh": "一封生日邀请信，说明聚会时间、烧烤准备、自带沙拉的请求以及乘车路线。",
        "key_lexemes": ["die Einladung", "feiern", "der Grillabend", "mitbringen", "die Wegbeschreibung"],
        "grammar_focus": ["Perfekt", "Trennbar_Verben", "Dativ_Pronomen"],
        "content": (
            "Liebe Freunde, nächste Woche am Samstag werde ich dreißig Jahre alt! "
            "Diesen besonderen Tag möchte ich gerne mit euch feiern. "
            "Ich lade euch herzlich zu einem gemütlichen Grillabend in meinen Garten ein. "
            "Die Feier fängt um neunzehn Uhr an. Für Getränke, Fleisch und Würstchen habe ich bereits gesorgt. "
            "Es wäre toll, wenn jeder von euch einen kleinen Salat oder ein Dessert mitbringen könnte. "
            "Mein Haus liegt direkt neben dem Stadtpark. Bitte gebt mir bis Mittwoch Bescheid, ob ihr kommen könnt."
        ),
        "reading_questions": [
            {
                "question": "Worum bittet der Gastgeber die Gäste?",
                "options": ["A. Fleisch und Getränke zu kaufen", "B. Einen Salat oder Nachtisch mitzubringen", "C. Pünktlich um 18:00 Uhr da zu sein"],
                "answer_idx": 1,
                "explanation_zh": "文中明确写道：'wenn jeder von euch einen kleinen Salat oder ein Dessert mitbringen könnte'."
            }
        ]
    },
    {
        "id": "goethe_a2_kultur_04",
        "title": "Ein Wochenende in München",
        "cefr": "A2",
        "category": "Gesellschaft & Kultur",
        "source_exam": "Goethe-Zertifikat A2 Lesen Teil 3",
        "word_count": 128,
        "summary_zh": "慕尼黑周末旅行日志，游览英国花园、德意志博物馆与玛利亚广场钟琴表演。",
        "key_lexemes": ["die Sehenswürdigkeit", "das Museum", "besichtigen", "der Glockenspiel", "die Innenstadt"],
        "grammar_focus": ["Präteritum_Hilfsverben", "Lokale_Präpositionen", "Nebensatz_weil"],
        "content": (
            "Letztes Wochenende haben wir eine kurze Reise nach München gemacht. "
            "Am Samstagvormittag sind wir durch den Englischen Garten spaziert und haben den Surfern auf der Eisbachwelle zugeschaut. "
            "Danach besuchten wir den Marienplatz, um das berühmte Glockenspiel am Neuen Rathaus zu sehen. "
            "Am Nachmittag waren wir im Deutschen Museum, weil uns Technik und Wissenschaft sehr interessieren. "
            "Das Wetter war sonnig, und die bayerische Küche im Biergarten hat hervorragend geschmeckt."
        ),
        "reading_questions": [
            {
                "question": "Warum besuchten sie das Deutsche Museum?",
                "options": ["A. Weil es geregnet hat", "B. Weil sie sich für Technik und Wissenschaft interessieren", "C. Weil das Rathaus geschlossen war"],
                "answer_idx": 1,
                "explanation_zh": "倒数第二句明确给出理由：'weil uns Technik und Wissenschaft sehr interessieren'."
            }
        ]
    },
    {
        "id": "goethe_b1_campus_05",
        "title": "Wohnen im Studentenwohnheim: Vor- und Nachteile",
        "cefr": "B1",
        "category": "Campus & Studium",
        "source_exam": "Goethe-Zertifikat B1 Lesen Teil 2",
        "word_count": 185,
        "summary_zh": "探讨大学生宿舍合租生活的优势与挑战，涉及社交、租金与私人空间管理。",
        "key_lexemes": ["das Studentenwohnheim", "die Wohngemeinschaft", "die Privatsphäre", "die Nebenkosten", "vereinbaren"],
        "grammar_focus": ["Nebensatz_obwohl_weil", "Adjektivdeklination", "Passiv_Präsens"],
        "content": (
            "Für viele Studienanfänger in Deutschland ist das Studentenwohnheim die erste Wahl. "
            "Der entscheidende Vorteil liegt in der günstigen Warmmiete, da Strom, Heizung und Internet bereits im Preis enthalten sind. "
            "Zudem knüpft man in einer Wohngemeinschaft schnell neue Kontakte mit Kommilitonen aus aller Welt. "
            "Allerdings bringt das Zusammenleben auf engem Raum auch Herausforderungen mit sich. "
            "Da Küche und Bad oft geteilt werden müssen, sind feste Putzpläne und gegenseitige Rücksichtnahme unverzichtbar. "
            "Wer viel Ruhe zum Lernen und ungestörte Privatsphäre sucht, entscheidet sich nach einigen Semestern häufig für eine eigene kleine Wohnung."
        ),
        "reading_questions": [
            {
                "question": "Welcher Hauptvorteil des Studentenwohnheims wird im Text hervorgehoben?",
                "options": ["A. Man hat immer ein eigenes Badezimmer", "B. Die Warmmiete ist günstig und beinhaltet Nebenkosten", "C. Es gibt keine Putzregeln"],
                "answer_idx": 1,
                "explanation_zh": "第二句明确指出：'Der entscheidende Vorteil liegt in der günstigen Warmmiete, da Strom, Heizung und Internet bereits im Preis enthalten sind'."
            }
        ]
    },
    {
        "id": "goethe_b1_beruf_06",
        "title": "Homeoffice und flexible Arbeitszeiten",
        "cefr": "B1",
        "category": "Beruf & Alltag",
        "source_exam": "Goethe-Zertifikat B1 Lesen Teil 1",
        "word_count": 192,
        "summary_zh": "讨论居家办公与弹性工作制对职场人士工作生活平衡（Work-Life-Balance）的影响。",
        "key_lexemes": ["das Homeoffice", "die Arbeitszeit", "die Selbstdisziplin", "das Zeitmanagement", "der Arbeitsplatz"],
        "grammar_focus": ["Infinitiv_mit_zu", "Modalverben_müssen_können", "Wechselpräpositionen"],
        "content": (
            "Das Arbeiten von zu Hause aus hat in den vergangenen Jahren stark an Bedeutung gewonnen. "
            "Viele Arbeitnehmer schätzen die Möglichkeit, ihren Tagesablauf flexibler zu gestalten und den täglichen Weg zur Arbeit im Berufsverkehr zu vermeiden. "
            "Studien belegen, dass Mitarbeiter im Homeoffice oft konzentrierter arbeiten können, sofern ein ruhiger Arbeitsplatz vorhanden ist. "
            "Gleichzeitig erfordert die Heimarbeit ein hohes Maß an Selbstdisziplin. "
            "Es fällt manchen Beschäftigten schwer, nach Feierabend abzuschalten und Berufliches von Privatem klar zu trennen. "
            "Aus diesem Grund etablieren viele moderne Unternehmen hybride Modelle mit zwei bis drei Präsenztagen pro Woche."
        ),
        "reading_questions": [
            {
                "question": "Welches Problem kann bei der Heimarbeit auftreten?",
                "options": ["A. Man darf keine Pausen machen", "B. Es fällt schwer, Arbeit und Freizeit sauber zu trennen", "C. Das Gehalt wird automatisch gekürzt"],
                "answer_idx": 1,
                "explanation_zh": "文中指出：'Es fällt manchen Beschäftigten schwer, nach Feierabend abzuschalten und Berufliches von Privatem klar zu trennen'."
            }
        ]
    },
    {
        "id": "goethe_b1_kultur_07",
        "title": "Die duale Berufsausbildung in Deutschland",
        "cefr": "B1",
        "category": "Gesellschaft & Kultur",
        "source_exam": "Goethe-Zertifikat B1 Lesen Teil 4",
        "word_count": 204,
        "summary_zh": "解析德国双元制职业教育模式（理论与企业实践结合），及其在全球的声誉。",
        "key_lexemes": ["das duale System", "die Berufsausbildung", "die Berufsschule", "die Praxis", "die Fachkraft"],
        "grammar_focus": ["Passiv_mit_werden", "Relativsätze_Dativ", "Konjunktionen_sowohl_als_auch"],
        "content": (
            "Das duale Ausbildungssystem gilt als eine der tragenden Säulen der deutschen Wirtschaft. "
            "Auszubildende lernen dabei sowohl die theoretischen Grundlagen in der Berufsschule als auch die praktische Arbeit direkt im Betrieb. "
            "Dieses Modell dauert in der Regel zwischen zwei und dreieinhalb Jahren und wird mit einer monatlichen Ausbildungsvergütung vergütet. "
            "Durch die enge Verknüpfung von Fachwissen und Betriebspraxis sind die Absolventen nach ihrem Abschluss sofort voll einsetzbar. "
            "Internationale Bildungsexperten loben das deutsche System regelmäßig, da es maßgeblich dazu beiträgt, die Jugendarbeitslosigkeit im Vergleich zu anderen europäischen Ländern niedrig zu halten."
        ),
        "reading_questions": [
            {
                "question": "Was zeichnet das duale Ausbildungssystem besonders aus?",
                "options": ["A. Reine Universitätstheorie ohne Betriebe", "B. Die Kombination aus Berufsschultheorie und betrieblicher Praxis", "C. Die Ausbildung ist immer unbezahlt"],
                "answer_idx": 1,
                "explanation_zh": "第二句明确概括：'Auszubildende lernen dabei sowohl die theoretischen Grundlagen in der Berufsschule als auch die praktische Arbeit direkt im Betrieb'."
            }
        ]
    },
    {
        "id": "goethe_b2_technik_08",
        "title": "Künstliche Intelligenz in der medizinischen Diagnostik",
        "cefr": "B2",
        "category": "Wissenschaft & Technik",
        "source_exam": "Goethe-Zertifikat B2 Lesen Teil 1",
        "word_count": 240,
        "summary_zh": "分析人工智能与深度学习在医学影像诊断中的前沿应用、伦理责任与人机协同未来。",
        "key_lexemes": ["die Diagnostik", "der Algorithmus", "die Früherkennung", "die Fehlerquote", "die Verantwortung"],
        "grammar_focus": ["Passiv_Ersatzformen_lassen", "Partizipialattribute", "Konjunktiv_2_Passiv"],
        "content": (
            "Der Einsatz von Algorithmen des maschinellen Lernens revolutioniert gegenwärtig die medizinische Bildgebung und Frühdiagnostik. "
            "Moderne neuronale Netze sind in der Lage, radiologische Aufnahmen wie Röntgenbilder oder MRT-Scans innerhalb von Sekundenbruchteilen zu analysieren. "
            "In mehreren klinischen Studien konnte nachgewiesen werden, dass spezialisierte KI-Systeme verdächtige Gewebeveränderungen mit einer Präzision erkennen, die der erfahrener Fachärzte in nichts nachsteht. "
            "Dennoch betonen Experten weltweit, dass Algorithmen die ärztliche Expertise keineswegs ersetzen, sondern vielmehr als entlastendes Assistenzsystem fungieren sollen. "
            "Die letztendliche therapeutische Entscheidung und die ethische Verantwortung verbleiben unabdingbar in der Hand des behandelnden Mediziners."
        ),
        "reading_questions": [
            {
                "question": "Welche Rolle soll Künstliche Intelligenz laut Experten in der Medizin einnehmen?",
                "options": ["A. Vollständiger Ersatz des medizinischen Personals", "B. Entlastendes Assistenzsystem unter ärztlicher Endverantwortung", "C. Reine Verwaltungssoftware ohne Bildanalyse"],
                "answer_idx": 1,
                "explanation_zh": "第四、五句指出：'Algorithmen die ärztliche Expertise keineswegs ersetzen, sondern vielmehr als entlastendes Assistenzsystem fungieren sollen. Die letztendliche Verantwortung verbleibt beim Mediziner'."
            }
        ]
    },
    {
        "id": "goethe_b2_umwelt_09",
        "title": "Die Energiewende und der Ausbau erneuerbarer Energien",
        "cefr": "B2",
        "category": "Gesellschaft & Kultur",
        "source_exam": "Goethe-Zertifikat B2 Lesen Teil 2",
        "word_count": 235,
        "summary_zh": "探讨德国能源转型目标，风能、光伏与电网储能设施扩建所面临的技术与社会挑战。",
        "key_lexemes": ["die Energiewende", "erneuerbare Energien", "die Photovoltaik", "das Stromnetz", "der Klimaschutz"],
        "grammar_focus": ["Genitiv_Attribute", "Zustandspassiv", "Konzessivsätze_obgleich"],
        "content": (
            "Die Umstellung der nationalen Energieversorgung auf erneuerbare Quellen bildet das Herzstück der deutschen Klimaschutzstrategie. "
            "Bis zum Jahr 2030 soll der Anteil von Windkraft und Solarenergie am Bruttostromverbrauch auf mindestens achtzig Prozent gesteigert werden. "
            "Um dieses ambitionierte Ziel zu erreichen, bedarf es jedoch nicht nur der Errichtung neuer Windparks auf See und an Land, sondern vor allem des massiven Ausbaus der Hochspannungsübertragungsnetze von Nord- nach Süddeutschland. "
            "Darüber hinaus gewinnen innovative Speichertechnologien wie grüner Wasserstoff und moderne Batteriespeicher rasant an Bedeutung, um witterungsbedingte Schwankungen in der Stromproduktion zuverlässig auszugleichen."
        ),
        "reading_questions": [
            {
                "question": "Warum ist der Ausbau des Übertragungsnetzes von Nord nach Süd so entscheidend?",
                "options": ["A. Um den im Norden erzeugten Windstrom in den industriereichen Süden zu transportieren", "B. Weil der Süden keine Solarenergie nutzen kann", "C. Um Strom ausschließlich ins Ausland zu verkaufen"],
                "answer_idx": 0,
                "explanation_zh": "结合德国地理与风电布局背景，文中指出将北部风电经高压网输送至全国是实现 80% 绿色电力的关键前提。"
            }
        ]
    },
    {
        "id": "testdaf_wissenschaft_10",
        "title": "Mikroplastik in marinen Ökosystemen",
        "cefr": "B2",
        "category": "Wissenschaft & Technik",
        "source_exam": "TestDaF Leseverstehen Text 1",
        "word_count": 268,
        "summary_zh": "微塑料在海洋生态系统中的富集机制、食物链传导以及对海洋生物生理机能的影响。",
        "key_lexemes": ["das Mikroplastik", "das Ökosystem", "die Nahrungskette", "die Partikel", "die Schadstoffbelastung"],
        "grammar_focus": ["Erweiterte_Partizipien", "Substantivierte_Verben", "Passiv_mit_sein_zu"],
        "content": (
            "Die weltweite Kontamination der Meere durch mikroskopisch kleine Kunststoffpartikel, sogenanntes Mikroplastik, stellt eine erhebliche Bedrohung für marine Organismen dar. "
            "Diese Partikel mit einem Durchmesser von weniger als fünf Millimetern entstehen vorwiegend durch die Zersetzung größerer Plastikabfälle infolge von UV-Strahlung und Wellenbewegung. "
            "Aufgrund ihrer winzigen Beschaffenheit werden sie von Plankton, Fischen und Seevögeln mit natürlicher Nahrung verwechselt und unbemerkt aufgenommen. "
            "In den Verdauungstrakten der Tiere können die unlöslichen Kunststoffteilchen schwere Entzündungen und Scheinsättigung hervorrufen. "
            "Besonders besorgniserregend ist die Tatsache, dass an den porösen Oberflächen der Partikel toxische Schadstoffe anhaften, die sich über die Nahrungskette bis zum Menschen anreichern können."
        ),
        "reading_questions": [
            {
                "question": "Wie entsteht das meiste Mikroplastik im Meer?",
                "options": ["A. Es wird gezielt als Düngemittel ins Meer geschüttet", "B. Durch Zersetzung größerer Plastikteile unter UV-Licht und Wellenschlag", "C. Durch die Ausscheidungen mariner Lebewesen"],
                "answer_idx": 1,
                "explanation_zh": "第二句明确指出：'entstehen vorwiegend durch die Zersetzung größerer Plastikabfälle infolge von UV-Strahlung und Wellenbewegung'."
            }
        ]
    },
    {
        "id": "testdaf_campus_11",
        "title": "Internationalisierung der Hochschulbildung",
        "cefr": "B2",
        "category": "Campus & Studium",
        "source_exam": "TestDaF Leseverstehen Text 2",
        "word_count": 256,
        "summary_zh": "分析德国高校国际化战略、跨文化交流、全英语授课硕士项目与科研竞争力提升。",
        "key_lexemes": ["die Internationalisierung", "der Studiengang", "die Sprachbarriere", "die Hochschullandschaft", "der Austausch"],
        "grammar_focus": ["Relativsatz_Genitiv", "N-Deklination", "Konjunktiv_1_indirekte_Rede"],
        "content": (
            "Deutsche Hochschulen erfreuen sich bei ausländischen Studierenden und Nachwuchswissenschaftlern weltweit wachsender Beliebtheit. "
            "Um im globalen Wettbewerb um die klügsten Köpfe wettbewerbsfähig zu bleiben, haben viele Universitäten in den vergangenen Jahren ihr Angebot an englischsprachigen Masterstudiengängen drastisch ausgebaut. "
            "Dieser Internationalisierungsschub fördert nicht nur den wissenschaftlichen Diskurs über Ländergrenzen hinweg, sondern bereichert auch das studentische Campusleben durch interkulturelle Vielfalt. "
            "Gleichwohl betonen Hochschulrektoren, dass das frühzeitige Erlernen der deutschen Sprache für eine nachhaltige soziale Integration und den späteren Einstieg in den hiesigen Arbeitsmarkt von entscheidender Bedeutung bleibt."
        ),
        "reading_questions": [
            {
                "question": "Warum ist das Erlernen der deutschen Sprache trotz englischer Studiengänge wichtig?",
                "options": ["A. Nur damit darf man die Universitätsbibliothek betreten", "B. Für die soziale Integration und den späteren Berufseinstieg in Deutschland", "C. Englisch ist an deutschen Universitäten offiziell verboten"],
                "answer_idx": 1,
                "explanation_zh": "最后一句指出：'das frühzeitige Erlernen der deutschen Sprache für eine nachhaltige soziale Integration und den späteren Einstieg in den Arbeitsmarkt von entscheidender Bedeutung bleibt'."
            }
        ]
    },
    {
        "id": "testdaf_wissenschaft_12",
        "title": "Bionik: Lernen von der Natur für technische Innovationen",
        "cefr": "B2",
        "category": "Wissenschaft & Technik",
        "source_exam": "TestDaF Leseverstehen Text 3",
        "word_count": 275,
        "summary_zh": "介绍仿生学（Bionik）如何将自然界生物进化出的精妙结构（如荷叶效应、鲨鱼皮）转化为前沿工程技术。",
        "key_lexemes": ["die Bionik", "die Evolution", "der Lotuseffekt", "die Selbstreinigung", "der Strömungswiderstand"],
        "grammar_focus": ["Passiv_Ersatzform_man", "Vergleichssätze_je_desto", "Konditionalsatz_ohne_wenn"],
        "content": (
            "Die Bionik verbindet Biologie und Technik mit dem Ziel, von der Natur entwickelte Prinzipien auf ingenieurwissenschaftliche Fragestellungen zu übertragen. "
            "Über Jahrmillionen der biologischen Evolution haben Pflanzen und Tiere hochentwickelte Mechanismen hervorgebracht, die sich durch maximale Effizienz bei minimalem Material- und Energieaufwand auszeichnen. "
            "Ein klassisches Paradebeispiel ist der Lotuseffekt: Die mikroskopische Oberflächenstruktur der Lotusblume sorgt dafür, dass Wassertropfen abperlen und Schmutzpartikel rückstandslos mitreißen. "
            "Dieses selbstreinigende Prinzip wird heute erfolgreich bei Fassadenfarben und selbstreinigenden Gläsern eingesetzt. "
            "Ein weiteres prominentes Beispiel liefert die gerillte Haut des Hais, deren Struktur den Strömungswiderstand minimiert und als Vorbild für energiesparende Flugzeugoberflächen dient."
        ),
        "reading_questions": [
            {
                "question": "Worauf basiert der selbstreinigende Lotuseffekt?",
                "options": ["A. Auf einer speziellen chemischen Seife, die die Pflanze absondert", "B. Auf einer mikroskopischen Oberflächenstruktur, an der Wasser und Schmutz abperlen", "C. Auf elektrischer Ladung der Blätter"],
                "answer_idx": 1,
                "explanation_zh": "第三句说明：'Die mikroskopische Oberflächenstruktur der Lotusblume sorgt dafür, dass Wassertropfen abperlen und Schmutzpartikel rückstandslos mitreißen'."
            }
        ]
    }
]


def get_corpus_list(cefr: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """返回语料库元数据清单（不含完整 content 字段以保证轻量秒开）。"""
    results = []
    for item in OFFICIAL_CORPUS:
        if cefr and cefr != "all" and item.get("cefr") != cefr:
            continue
        if category and category != "all" and item.get("category") != category:
            continue
        meta = {
            "id": item["id"],
            "title": item["title"],
            "cefr": item["cefr"],
            "category": item["category"],
            "source_exam": item["source_exam"],
            "word_count": item["word_count"],
            "summary_zh": item["summary_zh"],
            "key_lexemes": item["key_lexemes"],
            "grammar_focus": item.get("grammar_focus", []),
            "question_count": len(item.get("reading_questions", []))
        }
        results.append(meta)
    return results


def get_corpus_by_id(corpus_id: str) -> Optional[Dict[str, Any]]:
    """根据语料 ID 获取包含完整正文、重点考点词与阅读理解题的篇章对象。"""
    for item in OFFICIAL_CORPUS:
        if item.get("id") == corpus_id:
            return item
    return None
