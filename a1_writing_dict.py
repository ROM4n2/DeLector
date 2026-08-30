# -*- coding: utf-8 -*-
"""
Goethe-Zertifikat A1: Start Deutsch 1 - Schreiben Datasets.
Contains:
1. Teil 1 (Formular ausfüllen): 8 authentic examination form exercises with 5 fields each.
2. Teil 2 (Kurze E-Mail / Brief schreiben): 10 exam scenario prompts with Leitpunkte, sample emails, and useful phrases.
"""

from typing import Dict, List, Any

# ── Teil 1: Formular-Training (Anmeldeformular) ────────────────────────────────

A1_SCHREIBEN_TEIL1_EXERCISES: List[Dict[str, Any]] = [
    {
        "id": "form_01_sprachkurs",
        "title": "Sprachschule Deutschkurs Anmeldung",
        "scenario": "Ihre Freundin Eva Novak möchte im Sommer einen Deutschkurs in München besuchen. Helfen Sie ihr beim Ausfüllen des Anmeldeformulars.",
        "passage": "Eva Novak kommt aus Polen und wohnt seit zwei Monaten in Berlin, Schillerstraße 12. Sie ist am 15.08.1998 in Warschau geboren. Sie arbeitet als Journalistin und ist ledig. Sie möchte ab dem 01. Juli für vier Wochen einen Intensivkurs (20 Stunden pro Woche) in München machen und dort in einer Gastfamilie wohnen. Sie bezahlt den Kurs mit Kreditkarte.",
        "fields": [
            {
                "key": "familienname",
                "label": "1. Familienname",
                "expected": "Novak",
                "aliases": ["novak"],
                "tip": "Familienname ist der Nachname (Novak)."
            },
            {
                "key": "geburtsdatum",
                "label": "2. Geburtsdatum",
                "expected": "15.08.1998",
                "aliases": ["15.8.1998", "15. August 1998", "15.08.98"],
                "tip": "Geburtsdatum aus dem Text: 15.08.1998."
            },
            {
                "key": "wohnort",
                "label": "3. Wohnort / Straße",
                "expected": "Berlin, Schillerstraße 12",
                "aliases": ["Berlin, Schillerstr. 12", "Berlin", "Schillerstraße 12, Berlin"],
                "tip": "Wohnort ist Berlin, Straße ist Schillerstraße 12."
            },
            {
                "key": "beruf",
                "label": "4. Beruf",
                "expected": "Journalistin",
                "aliases": ["journalistin", "Journalist"],
                "tip": "Beruf aus dem Text: Journalistin."
            },
            {
                "key": "kursart",
                "label": "5. Kursart / Kursbeginn",
                "expected": "Intensivkurs (01.07.)",
                "aliases": ["Intensivkurs", "01.07.", "1. Juli", "Intensivkurs, 01. Juli"],
                "tip": "Kursart: Intensivkurs, Beginn: 01. Juli."
            }
        ]
    },
    {
        "id": "form_02_hotel",
        "title": "Hotelreservierung Hamburg",
        "scenario": "Ihr Kollege Marco Rossi reist geschäftlich nach Hamburg und muss das Hotelformular ausfüllen.",
        "passage": "Marco Rossi ist 32 Jahre alt, verheiratet und lebt in Rom. Für eine Konferenz reist er nach Hamburg. Er reist am 10. Mai an und bleibt drei Nächte bis zum 13. Mai. Er möchte ein Einzelzimmer mit Frühstück und Nichtraucher. Seine Telefonnummer ist 0039-3456789.",
        "fields": [
            {
                "key": "name",
                "label": "1. Name, Vorname",
                "expected": "Rossi, Marco",
                "aliases": ["Marco Rossi", "Rossi Marco"],
                "tip": "Name ist Rossi, Vorname Marco."
            },
            {
                "key": "ankunft",
                "label": "2. Anreisedatum",
                "expected": "10. Mai",
                "aliases": ["10.05.", "10.05.2026", "10.5."],
                "tip": "Anreisedatum ist der 10. Mai."
            },
            {
                "key": "naechte",
                "label": "3. Anzahl der Nächte",
                "expected": "3",
                "aliases": ["3 Nächte", "drei", "drei Nächte"],
                "tip": "Marco bleibt drei Nächte (10. bis 13. Mai)."
            },
            {
                "key": "zimmertyp",
                "label": "4. Zimmertyp",
                "expected": "Einzelzimmer (Nichtraucher)",
                "aliases": ["Einzelzimmer", "EZ", "Einzelzimmer Nichtraucher"],
                "tip": "Er möchte ein Einzelzimmer (Nichtraucher)."
            },
            {
                "key": "telefon",
                "label": "5. Telefonnummer",
                "expected": "0039-3456789",
                "aliases": ["00393456789", "+393456789"],
                "tip": "Telefonnummer aus dem Text: 0039-3456789."
            }
        ]
    },
    {
        "id": "form_03_stadtbibliothek",
        "title": "Anmeldung Stadtbibliothek Köln",
        "scenario": "Sara Meier möchte einen Bibliotheksausweis in Köln beantragen.",
        "passage": "Sara Meier, geboren am 03.11.2001 in Bern (Schweiz), studiert Informatik an der Universität zu Köln. Sie wohnt in der Luxemburger Str. 45, 50674 Köln. Ihre E-Mail-Adresse lautet sara.meier@web.de. Sie bezahlt die Jahresgebühr von 15 Euro bar.",
        "fields": [
            {
                "key": "vorname_nachname",
                "label": "1. Name, Vorname",
                "expected": "Meier, Sara",
                "aliases": ["Sara Meier", "Meier Sara"],
                "tip": "Nachname: Meier, Vorname: Sara."
            },
            {
                "key": "geburtsort",
                "label": "2. Geburtsort",
                "expected": "Bern",
                "aliases": ["Bern (Schweiz)", "Schweiz"],
                "tip": "Geburtsort ist Bern."
            },
            {
                "key": "plz_ort",
                "label": "3. PLZ / Wohnort",
                "expected": "50674 Köln",
                "aliases": ["50674", "Köln, 50674", "Köln"],
                "tip": "PLZ 50674, Ort Köln."
            },
            {
                "key": "email",
                "label": "4. E-Mail-Adresse",
                "expected": "sara.meier@web.de",
                "aliases": ["sara.meier@web.de"],
                "tip": "E-Mail-Adresse: sara.meier@web.de."
            },
            {
                "key": "beruf_status",
                "label": "5. Beruf / Status",
                "expected": "Studentin",
                "aliases": ["Student", "Studentin (Informatik)", "Informatikstudentin"],
                "tip": "Sara ist Studentin (studiert Informatik)."
            }
        ]
    },
    {
        "id": "form_04_arztpraxis",
        "title": "Patienten-Aufnahmebogen Arztpraxis Dr. Weber",
        "scenario": "Herr Ahmed Yilmaz geht zum ersten Mal zum Arzt in Frankfurt.",
        "passage": "Ahmed Yilmaz ist 45 Jahre alt, Techniker von Beruf und wohnt in der Hanauer Landstraße 88, 60314 Frankfurt am Main. Er ist bei der AOK gesetzlich versichert. Seine Mobilnummer ist 0176-98765432. Er hat seit drei Tagen starke Rückenschmerzen.",
        "fields": [
            {
                "key": "patient_name",
                "label": "1. Familienname, Vorname",
                "expected": "Yilmaz, Ahmed",
                "aliases": ["Ahmed Yilmaz", "Yilmaz Ahmed"],
                "tip": "Name: Yilmaz, Vorname: Ahmed."
            },
            {
                "key": "adresse",
                "label": "2. Straße, Hausnummer",
                "expected": "Hanauer Landstraße 88",
                "aliases": ["Hanauer Landstr. 88", "Hanauer Landstrasse 88"],
                "tip": "Hanauer Landstraße 88."
            },
            {
                "key": "krankenkasse",
                "label": "3. Krankenkasse",
                "expected": "AOK",
                "aliases": ["AOK gesetzlich", "AOK Versicherung"],
                "tip": "Krankenkasse ist die AOK."
            },
            {
                "key": "telefon",
                "label": "4. Telefon / Mobil",
                "expected": "0176-98765432",
                "aliases": ["017698765432", "0176 98765432"],
                "tip": "Mobilnummer: 0176-98765432."
            },
            {
                "key": "grund",
                "label": "5. Grund des Besuchs / Beschwerden",
                "expected": "Rückenschmerzen",
                "aliases": ["starke Rückenschmerzen", "Rueckenschmerzen"],
                "tip": "Beschwerden: Rückenschmerzen."
            }
        ]
    },
    {
        "id": "form_05_mietwagen",
        "title": "Autovermietung Sixt München",
        "scenario": "Herr Pierre Dubois mietet am Flughafen München ein Auto für ein Wochenende in den Bergen.",
        "passage": "Pierre Dubois (geboren am 22.04.1990 in Lyon, Frankreich) wohnt in München, Leopoldstraße 102. Er besitzt seit 12 Jahren den Führerschein Klasse B. Er möchte von Freitag, 14. Juli bis Sonntag, 16. Juli einen Kombi mit Automatikgetriebe und Vollkaskoversicherung mieten. Er zahlt mit Mastercard.",
        "fields": [
            {
                "key": "name",
                "label": "1. Name, Vorname",
                "expected": "Dubois, Pierre",
                "aliases": ["Pierre Dubois", "Dubois Pierre"],
                "tip": "Name: Dubois, Vorname: Pierre."
            },
            {
                "key": "geburtsdatum",
                "label": "2. Geburtsdatum",
                "expected": "22.04.1990",
                "aliases": ["22.4.1990", "22. April 1990"],
                "tip": "Geburtsdatum: 22.04.1990."
            },
            {
                "key": "mietdauer",
                "label": "3. Mietzeitraum",
                "expected": "14.07. - 16.07.",
                "aliases": ["14. Juli - 16. Juli", "14.07. bis 16.07.", "Freitag bis Sonntag", "14.-16. Juli"],
                "tip": "Von 14. Juli bis 16. Juli."
            },
            {
                "key": "fahrzeug",
                "label": "4. Fahrzeugtyp",
                "expected": "Kombi (Automatik)",
                "aliases": ["Kombi", "Kombi Automatik"],
                "tip": "Fahrzeugtyp: Kombi mit Automatik."
            },
            {
                "key": "zahlungsart",
                "label": "5. Zahlungsart",
                "expected": "Mastercard",
                "aliases": ["Kreditkarte", "Mastercard Kreditkarte"],
                "tip": "Zahlung mit Mastercard."
            }
        ]
    },
    {
        "id": "form_06_sportverein",
        "title": "Beitrittsformular TSV Sportverein Stuttgart",
        "scenario": "Elena Rostova möchte sich im Sportverein für Schwimmen und Yoga anmelden.",
        "passage": "Elena Rostova, 26 Jahre alt, lebt in Stuttgart, Hauptstr. 15, 70173 Stuttgart. Sie arbeitet als Architektin. Sie möchte ab dem 01. September montags am Yoga-Kurs und donnerstags am Schwimmtraining teilnehmen. Ihre Kontonummer für den Monatsbeitrag (35 Euro) ist DE44 6005 0101 1234 5678.",
        "fields": [
            {
                "key": "mitglied_name",
                "label": "1. Name, Vorname",
                "expected": "Rostova, Elena",
                "aliases": ["Elena Rostova", "Rostova Elena"],
                "tip": "Nachname: Rostova, Vorname: Elena."
            },
            {
                "key": "adresse",
                "label": "2. PLZ / Ort / Straße",
                "expected": "70173 Stuttgart, Hauptstr. 15",
                "aliases": ["70173 Stuttgart, Hauptstraße 15", "Hauptstr. 15, 70173 Stuttgart", "Stuttgart"],
                "tip": "Hauptstr. 15, 70173 Stuttgart."
            },
            {
                "key": "sportart",
                "label": "3. Gewünschte Sportarten",
                "expected": "Yoga und Schwimmen",
                "aliases": ["Yoga, Schwimmen", "Schwimmen und Yoga", "Yoga / Schwimmen"],
                "tip": "Sportarten: Yoga und Schwimmen."
            },
            {
                "key": "beginn",
                "label": "4. Mitgliedschaft ab",
                "expected": "01.09.",
                "aliases": ["01.09.2026", "1. September", "01. September", "1.9."],
                "tip": "Beginn ab 01. September."
            },
            {
                "key": "beitrag",
                "label": "5. Monatsbeitrag (EUR)",
                "expected": "35",
                "aliases": ["35 Euro", "35 €", "35 EUR"],
                "tip": "Monatsbeitrag beträgt 35 Euro."
            }
        ]
    },
    {
        "id": "form_07_vhs_kochkurs",
        "title": "Volkshochschule Dresden - Anmeldung Kochkurs",
        "scenario": "Jan Kowalski möchte einen Abendkurs 'Italienische Küche' an der VHS buchen.",
        "passage": "Jan Kowalski, geboren am 08.12.1985 in Danzig, wohnt in Dresden, Poststraße 9, 01067 Dresden. Er ist als Koch in einem Bistro tätig. Er meldet sich für den Kurs 'Italienische Küche für Genießer' an (Kurs-Nr. IT-402, freitags 18-21 Uhr, Beginn: 10. Oktober). Seine Telefonnummer ist 0351-889977.",
        "fields": [
            {
                "key": "teilnehmer",
                "label": "1. Familienname, Vorname",
                "expected": "Kowalski, Jan",
                "aliases": ["Jan Kowalski", "Kowalski Jan"],
                "tip": "Nachname: Kowalski, Vorname: Jan."
            },
            {
                "key": "geburtsort",
                "label": "2. Geburtsort",
                "expected": "Danzig",
                "aliases": ["Danzig (Polen)", "Gdansk"],
                "tip": "Geburtsort: Danzig."
            },
            {
                "key": "kursnummer",
                "label": "3. Kursnummer / Kurstitel",
                "expected": "IT-402 (Italienische Küche)",
                "aliases": ["IT-402", "Italienische Küche", "IT 402"],
                "tip": "Kurs-Nr. IT-402 (Italienische Küche)."
            },
            {
                "key": "kursstart",
                "label": "4. Kursbeginn",
                "expected": "10. Oktober",
                "aliases": ["10.10.", "10.10.2026", "10.10"],
                "tip": "Beginn am 10. Oktober."
            },
            {
                "key": "telefon",
                "label": "5. Telefon",
                "expected": "0351-889977",
                "aliases": ["0351889977", "0351 889977"],
                "tip": "Telefonnummer: 0351-889977."
            }
        ]
    },
    {
        "id": "form_08_fundbuero",
        "title": "Verlustmeldung Fundbüro DB Frankfurt",
        "scenario": "Frau Laura Santos hat im ICE ihren Rucksack vergessen.",
        "passage": "Laura Santos (geboren am 30.06.1995, aus Brasilien) reiste am 15. August mit dem ICE 772 von Frankfurt nach Mannheim. Sie hat im Zug ihren schwarzen Lederrucksack mit einem Laptop (Marke Lenovo) und einer Brille vergessen. Sie wohnt zzt. im Hotel Central, Zimmer 204 in Mannheim. Ihre Handynummer ist 0152-11223344.",
        "fields": [
            {
                "key": "verlierer",
                "label": "1. Name, Vorname",
                "expected": "Santos, Laura",
                "aliases": ["Laura Santos", "Santos Laura"],
                "tip": "Name: Santos, Vorname: Laura."
            },
            {
                "key": "zugnummer",
                "label": "2. Zugnummer / Reisedatum",
                "expected": "ICE 772 (15. August)",
                "aliases": ["ICE 772", "15.08., ICE 772", "15. August", "ICE772"],
                "tip": "ICE 772 am 15. August."
            },
            {
                "key": "gegenstand",
                "label": "3. Verlorener Gegenstand",
                "expected": "Schwarzer Lederrucksack",
                "aliases": ["Rucksack", "schwarzer Rucksack", "Lederrucksack"],
                "tip": "Schwarzer Lederrucksack."
            },
            {
                "key": "inhalt",
                "label": "4. Inhalt der Tasche",
                "expected": "Laptop (Lenovo) und Brille",
                "aliases": ["Laptop und Brille", "Laptop, Brille", "Lenovo Laptop"],
                "tip": "Inhalt: Laptop und Brille."
            },
            {
                "key": "kontakt",
                "label": "5. Telefonnummer",
                "expected": "0152-11223344",
                "aliases": ["015211223344", "0152 11223344"],
                "tip": "Handynummer: 0152-11223344."
            }
        ]
    }
]

A1_SCHREIBEN_TEIL1 = A1_SCHREIBEN_TEIL1_EXERCISES

# ── Teil 2: 30-Wort E-Mail / Brief Lab ────────────────────────────────────────

A1_SCHREIBEN_TEIL2_PROMPTS: List[Dict[str, Any]] = [
    {
        "id": "email_01_party_einladung",
        "scenario": "Einladung zur Geburtstagsparty",
        "prompt": "Sie haben am Samstag Geburtstag und möchten Ihre Freundin Lisa zu Ihrer Party einladen. Schreiben Sie an Lisa:",
        "leitpunkte": [
            "Warum schreiben Sie? (Geburtstagsparty)",
            "Wann und wo ist die Party?",
            "Was soll Lisa mitbringen? (z. B. Salat oder Getränke)"
        ],
        "sample_email": "Liebe Lisa,\n\nich lade dich herzlich zu meiner Geburtstagsparty am Samstag um 19 Uhr bei mir zu Hause ein. Kannst du vielleicht einen Salat oder etwas zu trinken mitbringen?\n\nViele Grüße\nAnna",
        "sample_translation": "亲爱的丽莎：\n\n我衷心邀请你参加我周六晚上 7 点在我家的生日聚会。你能顺便带一份沙拉或一些饮料来吗？\n\n祝好\n安娜",
        "useful_phrases": [
            "Ich lade dich herzlich zu ... ein.",
            "Die Party beginnt um ... Uhr.",
            "Kannst du bitte ... mitbringen?",
            "Ich hoffe, du kannst kommen."
        ]
    },
    {
        "id": "email_02_termin_absagen",
        "scenario": "Termin absagen (Arzt/Kurs)",
        "prompt": "Sie haben am Mittwoch um 10 Uhr einen Termin bei Dr. Müller, können aber nicht kommen. Schreiben Sie an die Praxis:",
        "leitpunkte": [
            "Grund des Schreibens (Termin am Mittwoch absagen)",
            "Warum können Sie nicht kommen? (krank / arbeiten)",
            "Neuer Termin (nächste Woche)"
        ],
        "sample_email": "Sehr geehrte Damen und Herren,\n\nleider kann ich meinen Termin am Mittwoch um 10 Uhr nicht wahrnehmen, weil ich arbeiten muss. Können wir den Termin auf nächste Woche verschieben?\n\nMit freundlichen Grüßen\nMax Mustermann",
        "sample_translation": "尊敬的女士们、先生们：\n\n很遗憾我因为要工作无法按约在周三上午 10 点赴约。请问我们能把预约推迟到下周吗？\n\n此致敬礼\n马克思·穆斯特曼",
        "useful_phrases": [
            "Leider kann ich meinen Termin am ... nicht wahrnehmen.",
            "Ich muss arbeiten / Ich bin krank.",
            "Können wir den Termin verschieben?",
            "Vielen Dank für Ihr Verständnis."
        ]
    },
    {
        "id": "email_03_wohnung_besichtigung",
        "scenario": "Wohnungsanzeige & Besichtigungstermin",
        "prompt": "Sie haben in der Zeitung eine 2-Zimmer-Wohnung gesehen und möchten sie besichtigen. Schreiben Sie an den Vermieter Herrn Becker:",
        "leitpunkte": [
            "Interesse an der 2-Zimmer-Wohnung",
            "Informationen über sich (Beruf / Personenzahl)",
            "Frage nach einem Besichtigungstermin"
        ],
        "sample_email": "Sehr geehrter Herr Becker,\n\nich interessiere mich sehr für Ihre 2-Zimmer-Wohnung. Ich arbeite als Ingenieur und suche eine Wohnung für mich allein. Wann kann ich die Wohnung besichtigen?\n\nMit besten Grüßen\nDavid Chen",
        "sample_translation": "尊敬的贝克尔先生：\n\n我对您的两居室公寓非常感兴趣。我是一名工程师，正在为自己一个人寻找住房。请问我什么时候可以看房？\n\n此致敬礼\n陈大卫",
        "useful_phrases": [
            "Ich interessiere mich sehr für Ihre Wohnung.",
            "Ich bin berufstätig als ...",
            "Wann wäre ein Besichtigungstermin möglich?",
            "Ich freue mich auf Ihre Antwort."
        ]
    },
    {
        "id": "email_04_krankmeldung_kurs",
        "scenario": "Krankmeldung beim Deutschkurs",
        "prompt": "Sie können heute wegen Fieber nicht zum Deutschkurs kommen. Schreiben Sie an Ihre Lehrerin Frau Schmidt:",
        "leitpunkte": [
            "Warum schreiben Sie? (heute krank / Fieber)",
            "Wie lange bleiben Sie zu Hause?",
            "Bitte um Hausaufgaben per E-Mail"
        ],
        "sample_email": "Liebe Frau Schmidt,\n\nich kann heute leider nicht zum Kurs kommen, weil ich hohes Fieber habe. Ich bleibe bis Mittwoch im Bett. Können Sie mir bitte die Hausaufgaben per E-Mail schicken?\n\nHerzliche Grüße\nMaria",
        "sample_translation": "亲爱的施密特老师：\n\n我今天很遗憾不能去上课，因为我发高烧了。我需要卧床休息到周三。请问您能把作业发到我邮箱吗？\n\n衷心祝好\n玛丽亚",
        "useful_phrases": [
            "Ich kann leider nicht zum Kurs kommen.",
            "Ich habe Fieber / bin krank.",
            "Können Sie mir die Hausaufgaben schicken?"
        ]
    },
    {
        "id": "email_05_hilfe_umzug",
        "scenario": "Hilfe beim Umzug erfragen",
        "prompt": "Sie ziehen am kommenden Wochenende um und brauchen Hilfe. Schreiben Sie an Ihren Freund Michael:",
        "leitpunkte": [
            "Umzug am Samstag um 10 Uhr",
            "Bitte um Hilfe beim Tragen von Kartons",
            "Einladung zum Pizzaessen danach"
        ],
        "sample_email": "Lieber Michael,\n\nich ziehe am Samstag um 10 Uhr in meine neue Wohnung um. Hast du Zeit und kannst mir beim Tragen helfen? Nach dem Umzug lade ich dich zum Pizzaessen ein.\n\nViele Grüße\nTom",
        "sample_translation": "亲爱的迈克尔：\n\n我周六上午 10 点搬新家。请问你有空帮我搬箱子吗？搬完家后我请你吃披萨。\n\n祝好\n汤姆",
        "useful_phrases": [
            "Ich ziehe am Samstag um.",
            "Kannst du mir beim Umzug helfen?",
            "Ich lade dich danach zum Essen ein."
        ]
    },
    {
        "id": "email_06_treffen_verschieben",
        "scenario": "Verabredung verschieben",
        "prompt": "Sie haben sich für Freitag mit Ihrer Kollegin Sarah verabredet, müssen aber länger arbeiten. Schreiben Sie an Sarah:",
        "leitpunkte": [
            "Entschuldigung (muss länger im Büro bleiben)",
            "Vorschlag für ein Treffen am Sonntag",
            "Frage nach Uhrzeit und Ort"
        ],
        "sample_email": "Liebe Sarah,\n\nes tut mir leid, aber ich muss am Freitag länger arbeiten und kann nicht kommen. Passt es dir vielleicht am Sonntag um 15 Uhr im Café Central?\n\nLiebe Grüße\nJulia",
        "sample_translation": "亲爱的莎拉：\n\n很抱歉，我周五必须加班不能来了。你看周日下午 3 点在中央咖啡馆见面合适吗？\n\n祝好\n朱莉娅",
        "useful_phrases": [
            "Es tut mir leid, dass ich nicht kommen kann.",
            "Ich muss länger arbeiten.",
            "Passt es dir am ... um ... Uhr?"
        ]
    },
    {
        "id": "email_07_hotelbuchung_anfrage",
        "scenario": "Hotelbuchung & Auskunft",
        "prompt": "Sie möchten im August mit Ihrer Familie Urlaub in Berlin machen. Schreiben Sie an das Hotel am Park:",
        "leitpunkte": [
            "Reservierung: 1 Doppelzimmer für 3 Nächte",
            "Anreise am 15. August",
            "Frage nach Frühstück und Parkplatz"
        ],
        "sample_email": "Sehr geehrte Damen und Herren,\n\nich möchte ein Doppelzimmer vom 15. bis 18. August reservieren. Ist das Frühstück im Preis enthalten und haben Sie einen Parkplatz für unser Auto?\n\nMit freundlichen Grüßen\nStefan Müller",
        "sample_translation": "尊敬的女士们、先生们：\n\n我想预订 8 月 15 日至 18 日的一间双人间。请问房价包含早餐吗？你们有供我们停车的停车位吗？\n\n此致敬礼\n施特凡·穆勒",
        "useful_phrases": [
            "Ich möchte ein Doppelzimmer reservieren.",
            "Ist das Frühstück inklusive?",
            "Haben Sie einen Parkplatz?"
        ]
    },
    {
        "id": "email_08_deutschkurs_auskunft",
        "scenario": "Informationen über Deutschkurs A2",
        "prompt": "Sie haben den Kurs A1 bestanden und möchten Informationen über den Folgekurs A2. Schreiben Sie an die Sprachschule:",
        "leitpunkte": [
            "A1 erfolgreich abgeschlossen",
            "Wann beginnt der nächste A2-Abendkurs?",
            "Wie viel kostet der Kurs?"
        ],
        "sample_email": "Sehr geehrte Damen und Herren,\n\nich habe gerade den A1-Kurs abgeschlossen und möchte nun A2 lernen. Wann beginnt der nächste A2-Abendkurs und wie viel kostet die Anmeldung?\n\nMit besten Grüßen\nElena Weber",
        "sample_translation": "尊敬的女士们、先生们：\n\n我刚学完 A1 课程，现在想继续学习 A2。请问下一期 A2 晚班什么时候开课，报名费用是多少？\n\n此致敬礼\n埃琳娜·韦伯",
        "useful_phrases": [
            "Ich habe den Kurs abgeschlossen.",
            "Wann beginnt der nächste Kurs?",
            "Wie hoch sind die Kursgebühren?"
        ]
    },
    {
        "id": "email_09_fundsache_anfrage",
        "scenario": "Nachfrage verlorene Tasche im Restaurant",
        "prompt": "Sie haben gestern Abend Ihre schwarze Tasche im Restaurant 'Zur Post' vergessen. Schreiben Sie an das Restaurant:",
        "leitpunkte": [
            "Gestern Abend bei Ihnen gegessen (Tisch 4)",
            "Schwarze Ledertasche mit Schlüssel vergessen",
            "Wann kann ich die Tasche abholen?"
        ],
        "sample_email": "Sehr geehrte Damen und Herren,\n\ngestern Abend habe ich an Tisch 4 gegessen und meine schwarze Tasche vergessen. Darin sind meine Hausschlüssel. Haben Sie die Tasche gefunden und wann kann ich sie abholen?\n\nMit freundlichen Grüßen\nKlaus Braun",
        "sample_translation": "尊敬的女士们、先生们：\n\n昨晚我在 4 号桌就餐，不小心把黑色包落下了。里面有我的钥匙。请问你们找到了吗？我什么时候可以来取？\n\n此致敬礼\n克劳斯·布劳恩",
        "useful_phrases": [
            "Ich habe gestern meine Tasche vergessen.",
            "Haben Sie den Gegenstand gefunden?",
            "Wann kann ich vorbeikommen?"
        ]
    },
    {
        "id": "email_10_geburtstagsglueckwunsch",
        "scenario": "Glückwünsche zum Geburtstag",
        "prompt": "Ihr Kollege Markus hat heute Geburtstag. Schreiben Sie ihm eine kurze Glückwunsch-E-Mail:",
        "leitpunkte": [
            "Herzliche Glückwünsche zum Geburtstag",
            "Viel Gesundheit und Erfolg im neuen Jahr",
            "Treffen auf einen Kaffee in der Pause"
        ],
        "sample_email": "Lieber Markus,\n\nich gratuliere dir ganz herzlich zum Geburtstag! Ich wünsche dir viel Gesundheit, Glück und Erfolg. Trinken wir heute in der Mittagspause zusammen einen Kaffee?\n\nBeste Grüße\nDaniel",
        "sample_translation": "亲爱的马库斯：\n\n衷心祝你生日快乐！祝你身体健康、幸福顺遂、工作顺利。今天午休我们一起喝杯咖啡好吗？\n\n祝好\n丹尼尔",
        "useful_phrases": [
            "Herzlichen Glückwunsch zum Geburtstag!",
            "Ich wünsche dir alles Gute und viel Gesundheit.",
            "Lass uns bald feiern."
        ]
    }
]

A1_SCHREIBEN_TEIL2 = A1_SCHREIBEN_TEIL2_PROMPTS

for _ex in A1_SCHREIBEN_TEIL1_EXERCISES:
    for _fld in _ex["fields"]:
        if "answer" not in _fld and "expected" in _fld:
            _fld["answer"] = _fld["expected"]
        if "expected" not in _fld and "answer" in _fld:
            _fld["expected"] = _fld["answer"]


