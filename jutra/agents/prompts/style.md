Analizujesz wylacznie **styl mowy** uzytkownika na podstawie ponizszej wiadomosci zawierajacej jego wypowiedzi (po polsku lub mieszany jezyk).

**Zadanie:** Zwroc TYLKO jeden obiekt JSON (bez markdown, bez komentarzy).

Pola (wszystkie wymagane):

- formality: string, jedna z wartosci "casual", "neutral", "formal"
- tone: string, 1-2 zdania PL opisujace ogolny ton
- sentence_length: string, jedna z "short", "medium", "long"
- typical_openers: tablica stringow (max 5)
- fillers: tablica stringow (max 8)
- signature_phrases: tablica stringow (max 6)
- vocabulary_notes: string — slang, anglicyzmy, skroty
- emoji_usage: string, jedna z "none", "rare", "frequent"
- examples: tablica 1-3 krotkich doslownych cytatow z tekstu uzytkownika
- updated_at: pusty string "" (uzupelni backend)

Jesli tekstow jest malo, zwroc najlepszy mozliwy szkielet (nie wymyslaj faktow o zyciu — tylko styl).
