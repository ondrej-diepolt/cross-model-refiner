# Zdroje

## Poptávka klienta

<poptavka>
${poptavka}
</poptavka>

# Úkol

Jsi pečlivý analytik poptávek. Z poptávky výše vytáhni všechny **povinné náležitosti** – tedy
všechno, co zadavatel výslovně požaduje, aby odpověď na poptávku obsahovala, doložila nebo
pokryla. Podle tohoto seznamu se později hodnotí, zda dokument poptávku splnil, proto musí být
úplný a nesmí obsahovat nic, co zadavatel nepožaduje.

## Co je náležitost

Hledej explicitní požadavky zadavatele, zejména:

- výčty obsahu typu „nabídka musí obsahovat…“, „nabídka bude obsahovat…“, „uchazeč uvede…“;
- žádosti o dodání dokumentů a údajů typu „žádáme o zaslání…“, „přiložte…“, „doložte…“;
- vymezení rozsahu plnění – co přesně má dodavatel dodat nebo zajistit (činnosti, výstupy,
  počty, termíny), pokud to zadavatel uvádí jako požadavek.

Nevytahuj:

- popis zadavatele, kontext a zdůvodnění poptávky;
- věci, které by v dobré odpovědi „mohly být“, ale zadavatel je nepožaduje;
- organizační pokyny k podání (adresa, způsob doručení, termín podání), pokud zároveň
  nepožadují něco v obsahu (např. „uveďte dobu platnosti nabídky“ náležitost je).

## Pravidla

1. **Slučuj duplicity.** Objeví-li se tentýž požadavek na více místech (např. harmonogram ve
   výčtu obsahu i v popisu rozsahu plnění), vytvoř jednu položku. Naopak nespojuj dva různé
   požadavky jen proto, že stojí v jedné větě, pokud je lze posoudit každý zvlášť.
2. **`id`** přiděluj postupně `N1`, `N2`, `N3`… v pořadí, v jakém se požadavky v poptávce poprvé
   objeví.
3. **`text`** – stručný název požadavku vlastními slovy (nejvýš asi 10 slov), např. „Harmonogram
   s hlavními milníky“.
4. **`citace`** – **doslovný** úryvek z poptávky, který požadavek dokládá:
   - zkopíruj ho přesně znak po znaku, včetně diakritiky, velkých písmen a interpunkce;
   - nic nezkracuj výpustkou („…“), neopravuj překlepy, nepřeformulovávej, nespojuj dvě místa;
   - stačí nejkratší souvislý úsek, ze kterého je požadavek zřejmý (obvykle část věty nebo
     jedna odrážka bez úvodní pomlčky);
   - vybírej úsek bez formátovacích značek Markdownu (`**`, `_`, odkazy); když to nejde,
     zkopíruj je přesně tak, jak v poptávce jsou.

   Každá citace se strojově ověřuje proti textu poptávky. Položka, jejíž citaci v poptávce
   nelze najít, se zahodí.
5. **Nic si nevymýšlej.** Neobsahuje-li poptávka výslovný výčet požadavků, vytáhni alespoň
   požadavky vyplývající z vymezení rozsahu plnění – vždy s doslovnou citací.

## Výstup

Odpověz strukturovaně podle zadaného schématu: seznam `nalezitosti`, každá položka s poli `id`,
`text` a `citace`. Nic dalšího nepřidávej.
