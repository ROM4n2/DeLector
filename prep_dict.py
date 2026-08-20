# -*- coding: utf-8 -*-
"""AI 批量生成的德语动词/形容词固定介词搭配表（auto-generated）。

Schema: lemma -> ((介词, 格, 中文义, 例句), ...)
值是**元组的元组**：一个词头可带多个介词且意思不同
（bestehen auf 坚持 / aus 由…组成 / in 在于），单值会丢义项。

键全小写、反身动词不带 sich（freuen 而非 sich freuen），
以便直接匹配 spaCy 的 lemma 输出。
手动改会丢：必考搭配请改 tools/build_prep.py 的 SEED_COLLOCATIONS，
长尾靠 AI 生成，两者由 tools/build_prep.py 合并（seed 优先）。
"""

PREP_COLLOCATIONS = {  # 47 词条 / 56 条搭配 · 已问过 47 词 · seed 47 词 + AI 长尾
    "abhängig": (("von", "Dat", "依赖于", "Der Erfolg ist von vielen Faktoren abhängig."),),
    "achten": (("auf", "Akk", "注意", "Bitte achten Sie auf die Verkehrszeichen."),),
    "anfangen": (("mit", "Dat", "开始做", "Wir fangen mit der Übung an."),),
    "antworten": (("auf", "Akk", "回答", "Er antwortet auf die Frage."),),
    "aufhören": (("mit", "Dat", "停止做", "Er hört mit dem Rauchen auf."),),
    "bekannt": (("für", "Akk", "因…闻名", "Die Stadt ist für ihre Architektur bekannt."),),
    "bereit": (("zu", "Dat", "愿意", "Er ist zu einem Kompromiss bereit."),),
    "beschäftigen": (("mit", "Dat", "(sich)从事/研究", "Ich beschäftige mich mit deutscher Literatur."),),
    "bestehen": (("auf", "Dat", "坚持", "Er besteht auf seiner Meinung."), ("aus", "Dat", "由…组成", "Das Team besteht aus fünf Personen."), ("in", "Dat", "在于", "Die Aufgabe besteht in der Analyse der Daten.")),
    "beteiligen": (("an", "Dat", "(sich)参与", "Er beteiligt sich an der Diskussion."),),
    "bewerben": (("um", "Akk", "(sich)申请职位", "Er bewirbt sich um die Stelle."), ("bei", "Dat", "(sich)向…求职", "Sie bewirbt sich bei einer Bank.")),
    "bitten": (("um", "Akk", "请求", "Er bittet mich um Hilfe."),),
    "böse": (("auf", "Akk", "生气", "Sie ist böse auf ihn."),),
    "dankbar": (("für", "Akk", "感激", "Ich bin dir für deine Hilfe dankbar."),),
    "denken": (("an", "Akk", "想到", "Ich denke oft an meine Familie."),),
    "einverstanden": (("mit", "Dat", "同意", "Ich bin mit dem Plan einverstanden."),),
    "entschuldigen": (("für", "Akk", "(sich)为…道歉", "Ich entschuldige mich für die Verspätung."), ("bei", "Dat", "(sich)向…道歉", "Er entschuldigt sich bei seinem Chef.")),
    "erinnern": (("an", "Akk", "(sich)记得", "Ich erinnere mich an den Tag."),),
    "freuen": (("auf", "Akk", "(sich)期待", "Ich freue mich auf die Ferien."), ("über", "Akk", "(sich)为…高兴", "Sie freut sich über das Geschenk.")),
    "fähig": (("zu", "Dat", "有能力", "Er ist zu großen Leistungen fähig."),),
    "gehören": (("zu", "Dat", "属于", "Dieses Buch gehört zu meiner Sammlung."),),
    "gewöhnen": (("an", "Akk", "(sich)习惯于", "Ich gewöhne mich an das Klima."),),
    "glauben": (("an", "Akk", "相信", "Sie glaubt an den Erfolg."),),
    "gratulieren": (("zu", "Dat", "祝贺", "Wir gratulieren ihr zu ihrem Erfolg."),),
    "helfen": (("bei", "Dat", "帮忙做", "Er hilft mir bei den Hausaufgaben."),),
    "hoffen": (("auf", "Akk", "希望", "Wir hoffen auf besseres Wetter."),),
    "interessieren": (("für", "Akk", "(sich)对…感兴趣", "Er interessiert sich für Politik."),),
    "kümmern": (("um", "Akk", "(sich)照顾", "Sie kümmert sich um die Kinder."),),
    "leiden": (("an", "Dat", "患（病）", "Er leidet an einer Allergie."), ("unter", "Dat", "受…之苦", "Sie leidet unter dem Lärm.")),
    "neugierig": (("auf", "Akk", "好奇", "Ich bin neugierig auf das Ergebnis."),),
    "rechnen": (("mit", "Dat", "预计", "Wir rechnen mit Regen."),),
    "schützen": (("vor", "Dat", "保护免受", "Die Creme schützt vor der Sonne."),),
    "sorgen": (("für", "Akk", "照料/负责", "Sie sorgt für ihre kranke Mutter."), ("um", "Akk", "(sich)担心", "Ich sorge mich um dich.")),
    "sprechen": (("über", "Akk", "谈论", "Wir sprechen über die Prüfung."), ("mit", "Dat", "与…交谈", "Ich spreche mit dem Lehrer."), ("von", "Dat", "提到", "Sie spricht oft von ihrer Reise.")),
    "stolz": (("auf", "Akk", "为…自豪", "Die Eltern sind stolz auf ihre Tochter."),),
    "teilnehmen": (("an", "Dat", "参加", "Sie nimmt an der Konferenz teil."),),
    "träumen": (("von", "Dat", "梦想", "Sie träumt von einer Weltreise."),),
    "unterhalten": (("über", "Akk", "(sich)聊起", "Wir unterhalten uns über Musik."),),
    "verantwortlich": (("für", "Akk", "对…负责", "Sie ist für das Projekt verantwortlich."),),
    "verlassen": (("auf", "Akk", "(sich)信赖", "Du kannst dich auf mich verlassen."),),
    "verzichten": (("auf", "Akk", "放弃", "Wir verzichten auf den Urlaub."),),
    "vorbereiten": (("auf", "Akk", "(sich)为…做准备", "Ich bereite mich auf die Prüfung vor."),),
    "warten": (("auf", "Akk", "等待", "Ich warte auf den Bus."),),
    "zufrieden": (("mit", "Dat", "满意", "Ich bin mit dem Ergebnis zufrieden."),),
    "zweifeln": (("an", "Dat", "怀疑", "Er zweifelt an seiner Entscheidung."),),
    "ärgern": (("über", "Akk", "(sich)为…生气", "Er ärgert sich über den Fehler."),),
    "überzeugt": (("von", "Dat", "确信", "Er ist von seiner Idee überzeugt."),),
}
