// source: https://github.com/lorenzodifuccia/safaribooks/issues/358#issuecomment-2451495139

copy(JSON.stringify(document.cookie.split(';').map(c => c.split('=')).map(i => [i[0].trim(), i[1].trim()]).reduce((r, i) => {r[i[0]] = i[1]; return r;}, {})))
