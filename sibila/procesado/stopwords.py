"""Stopwords ES/EN congeladas como DATO (derivadas de las listas clásicas
Snowball ES/EN, empotradas: no son dependencia NLTK).

D-L2: content word = palabra (D-L1) de ≥3 letras que NO está en la lista del
idioma. Idioma distinto de es/en o None → stopwords = ∅ (provisional Fase 1).

STOPWORDS_VERSION (rev. H4): los bigramas/trigramas y los cluster_key dependen
de estas listas; cambiar una lista = subir STOPWORDS_VERSION = re-procesado
completo, igual que BOT_VERSION.
"""

STOPWORDS_VERSION = "sw-1"

# Derivada de la lista Snowball de español (literales congelados, "sw-1").
ES = frozenset(
    "a ante bajo cabe con contra de desde durante en entre hacia hasta para "
    "por segun sin so sobre tras versus via el la los las un una unos unas "
    "este esta estos estas ese esa esos esas aquel aquella aquellos aquellas "
    "esto eso aquello mi mis tu tus su sus nuestro nuestra nuestros nuestras "
    "vuestro vuestra vuestros vuestras suyo suya suyos suyas mio mia mios mias "
    "tuyo tuya tuyos tuyas me te se nos os le les lo yo tu el ella usted "
    "nosotros nosotras vosotros vosotras ellos ellas ustedes quien quienes "
    "que cual cuales cuyo cuya cuyos cuyas como cuando donde cuanto cuanta "
    "cuantos cuantas algo nada alguien nadie ninguno ninguna algun alguna "
    "algunos algunas varios varias mucho mucha muchos muchas poco poca pocos "
    "pocas todo toda todos todas otro otra otros otras mismo misma mismos "
    "mismas tanto tanta tantos tantas tal tales cada ser soy eres es somos "
    "sois son era eras eramos erais eran fui fuiste fue fuimos fuisteis fueron "
    "sere seras sera seremos sereis seran siendo sido estar estoy estas esta "
    "estamos estais estan estaba estabas estabamos estabais estaban estuve "
    "estuviste estuvo estuvimos estuvisteis estuvieron estare estaras estara "
    "estaremos estareis estaran estando estado haber he has ha hemos habeis "
    "han habia habias habiamos habiais habian hube hubiste hubo hubimos "
    "hubisteis hubieron habre habras habra habremos habreis habran habiendo "
    "habido hay tener tengo tienes tiene tenemos teneis tienen tenia tenias "
    "teniamos teniais tenian tuve tuviste tuvo tuvimos tuvisteis tuvieron "
    "tendre tendras tendra tendremos tendreis tendran teniendo tenido hacer "
    "hago haces hace hacemos haceis hacen hacia hacias haciamos haciais hacian "
    "hice hiciste hizo hicimos hicisteis hicieron hare haras hara haremos "
    "hareis haran haciendo hecho poder puedo puedes puede podemos podeis "
    "pueden podia podias podiamos podiais podian pude pudiste pudo pudimos "
    "pudisteis pudieron podre podras podra podremos podreis podran pudiendo "
    "podido ir voy vas va vamos vais van iba ibas ibamos ibais iban fui irse "
    "yendo ido decir digo dices dice decimos decis dicen decia decias deciamos "
    "deciais decian dije dijiste dijo dijimos dijisteis dijeron dire diras "
    "dira diremos direis diran diciendo dicho ver veo ves ve vemos veis ven "
    "veia veias veiamos veiais veian vi viste vio vimos visteis vieron vere "
    "veras vera veremos vereis veran viendo visto dar doy das da damos dais "
    "dan daba dabas dabamos dabais daban di diste dio dimos disteis dieron "
    "dare daras dara daremos dareis daran dando dado saber se sabes sabe "
    "sabemos sabeis saben sabia sabias sabiamos sabiais sabian supe supiste "
    "supo supimos supisteis supieron sabre sabras sabra sabremos sabreis sabran "
    "sabiendo sabido querer quiero quieres quiere queremos quereis quieren "
    "queria querias queriamos queriais querian quise quisiste quiso quisimos "
    "quisisteis quisieron querre querras querra querremos querreis querran "
    "queriendo querido y o ni pero mas sino si no si tambien tampoco aun "
    "aunque porque pues ya muy mas menos tan asi aqui ahi alli ahora entonces "
    "despues antes siempre nunca jamas hoy ayer mañana ademas incluso solo "
    "solamente apenas casi quizas quiza acaso segun embargo siquiera".split()
)

# Derivada de la lista Snowball de inglés (literales congelados, "sw-1").
EN = frozenset(
    "a an and are as at be but by for if in into is it no not of on or such "
    "that the their then there these they this to was will with i me my we "
    "our you your he him his she her its them us am were been being have has "
    "had having do does did doing would should could ought i'm you're he's "
    "she's it's we're they're i've you've we've they've i'd you'd he'd she'd "
    "we'd they'd i'll you'll he'll she'll we'll they'll isn't aren't wasn't "
    "weren't hasn't haven't hadn't doesn't don't didn't won't wouldn't shan't "
    "shouldn't can't cannot couldn't mustn't let's that's who's what's here's "
    "there's when's where's why's how's because until while of about against "
    "between through during before after above below up down out off over "
    "under again further then once here there when where why how all any both "
    "each few more most other some such only own same so than too very can "
    "just don now".split()
)


def stopwords(lang: str | None) -> frozenset:
    """Lista del idioma; ∅ si lang no es 'es'/'en' o es None (D-L2, Fase 1)."""
    if lang == "es":
        return ES
    if lang == "en":
        return EN
    return frozenset()
