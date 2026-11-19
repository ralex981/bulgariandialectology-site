"""Alphabetical order for the site's Latin transcription.

Follows the symbol order on the site's "Principles of Transcription" page, with consonants
and vowels merged as in English and z added before ž:

    a ɑ b c č d dz dž e ɛ e̝ f ɸ g h i ɨ y j k l m n o ɔ o̝ p r s š t u ɤ ʌ ɯ ə ə̝ v β w x z ž

Stress marks and other diacritics that only modify a letter (à, ò, ŭ, ə̥, n', ...) are
ignored at first, so forms with and without them sort together; they only decide the order
between forms that are otherwise identical. Cyrillic (lexemes) uses the Bulgarian alphabet.

The same table is written to assets/collation.js so the browser sorts the same way."""
import json
import unicodedata

ALPHABET = ['a', 'ɑ', 'b', 'c', 'č', 'd', 'dz', 'dž', 'e', 'ɛ', 'e̝', 'f', 'ɸ', 'g', 'h', 'i', 'ɨ', 'y', 'j', 'k',
            'l', 'm', 'n', 'o', 'ɔ', 'o̝', 'p', 'r', 's', 'š', 't', 'u', 'ɤ', 'ʌ', 'ɯ', 'ə', 'ə̝', 'v', 'β', 'w',
            'x', 'z', 'ž']
# characters not in the table, sorted next to the letter they are a variant of
VARIANTS = {'æ': 'ɑ', 'ɣ': 'g', 'ı': 'i', 'ⁱ': 'i', 'ᶤ': 'ɨ', 'ɰ': 'ɯ', 'ᵚ': 'ɯ', 'ᵊ': 'ə',
            'ә': 'ə',      # Cyrillic schwa typed by mistake for ə
            'q': 'k'}
# combining marks that are part of a letter in the table (e̝, o̝, ə̝, č, š, ž); all others are ignorable
LETTER_MARKS = {'̝', '̌'}
BG = 'абвгдежзийклмнопрстуфхцчшщъьюя'


def _tables():
    rank = {}
    for i, sym in enumerate(ALPHABET):
        rank[unicodedata.normalize('NFD', sym)] = i + 1
    for v, base in VARIANTS.items():
        rank[unicodedata.normalize('NFD', v)] = rank[unicodedata.normalize('NFD', base)]
    for i, ch in enumerate(BG):
        rank[ch] = 100 + i
    return rank


RANK = _tables()
MAXLEN = max(len(k) for k in RANK)


def key(s):
    """Sort key: (primary letters, then the full form as a tie-breaker)."""
    s = unicodedata.normalize('NFD', (s or '').casefold())
    s = s.replace('ѐ', 'е').replace('ѝ', 'и')
    prim, i = [], 0
    while i < len(s):
        ch = s[i]
        if unicodedata.combining(ch) and ch not in LETTER_MARKS:
            i += 1; continue
        for L in range(MAXLEN, 0, -1):
            seg = s[i:i + L]
            if seg in RANK:
                # a letter-mark sequence only counts when it is in the table (e̝); a bare caron etc. is skipped
                prim.append(RANK[seg]); i += L; break
        else:
            if ch.isalnum():
                prim.append(1000 + ord(ch))       # anything else: after the alphabet, by code point
            i += 1
    return (tuple(prim), s)


def js():
    """Browser version of key(): returns a string that compares correctly with < and >."""
    table = json.dumps({k: v for k, v in RANK.items()}, ensure_ascii=False)
    return ("window.BDLT=window.BDLT||{};(function(){var BDLT=window.BDLT,R=" + table + ",M=" + str(MAXLEN) +
            ",LM={'\\u031d':1,'\\u030c':1};"
            "function comb(c){return /[\\u0300-\\u036f]/.test(c);}"
            "BDLT.collateKey=function(s){s=String(s==null?'':s).toLowerCase().normalize('NFD');var p='',i=0;"
            "while(i<s.length){var c=s[i];if(comb(c)&&!LM[c]){i++;continue;}var hit=false;"
            "for(var L=M;L>0;L--){var g=s.substr(i,L);if(R[g]!==undefined){p+=String.fromCharCode(0x100+R[g]);i+=L;hit=true;break;}}"
            "if(!hit){if(/[\\p{L}\\p{N}]/u.test(c))p+=String.fromCharCode(0x2000+c.charCodeAt(0));i++;}}"
            "return p+'\\u0001'+s;};"
            "BDLT.collate=function(a,b){a=BDLT.collateKey(a);b=BDLT.collateKey(b);return a<b?-1:a>b?1:0;};})();\n")


if __name__ == '__main__':
    words = ['xùxla', 'Huhla', 'bràt', 'brat', 'bɑba', 'ʌbe', 'zìma', 'žena', 'dzvèzda', 'dvor', 'dževàp', 'ɛ̀ne',
             'e̝ste', 'ftor', 'Ìhtiman', 'ɨmɑ', 'yla', 'Vŭrbina', 'Vǔrbina', 'ətə', 'tùk', 'Šumen', 'Sŭrnica']
    print(sorted(words, key=key))
