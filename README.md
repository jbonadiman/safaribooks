# SafariBooks
Download and generate *EPUB* of your favorite books from [*Safari Books Online*](https://www.safaribooksonline.com) library.  
I'm not responsible for the use of this program, this is only for *personal* and *educational* purpose.  
Before any usage please read the *O'Reilly*'s [Terms of Service](https://learning.oreilly.com/terms/).  

<a href='https://ko-fi.com/Y8Y0MPEGU' target='_blank'><img height='80' style='border:0px;height:60px;' src='https://storage.ko-fi.com/cdn/kofi6.png?v=6' border='0' alt='Buy Me a Coffee at ko-fi.com'/></a>

## How it works
`safaribooks.py` downloads the book through the v2 API, `/api/v2/epubs/urn:orm:book:<ID>/files/`. That endpoint lists **every file of the EPUB as O'Reilly published it** (package document, NCX, stylesheets, fonts, images and chapters), so the script fetches those files and zips them back together instead of rebuilding the book from rendered HTML. The publisher's manifest, reading order, folder layout, stylesheets, fonts and table of contents are kept.

What is changed on the way, all of it with an opt-out:

- Anti-bot markup that Akamai injects into pages (`<script>`, root-relative `<link>`, `#sec-overlay`) is removed.
- The title and language of the OPF are replaced with those of the edition you downloaded (translated books ship the English ones). A missing author or publisher is filled in from the search API, or from the NCX `docAuthor`.
- Images are converted to JPEG, unused ones are dropped, and Calibre's `ebook-polish` runs if it is installed. Skip all of it with `--no-optimize-images`.
- The `color` property is removed from stylesheets and inline styles so light/dark reader themes keep working. Skip it with `--no-optimize-css`.
- Fixed-layout (PDF-style) books are detected and declared `pre-paginated`, with the page size pinned, the publisher's `scale()` baked into the numbers, and a nav document built from the NCX. Colours are left alone there, and the polish step is skipped.

Downloads are resumable. Files already in `Books/<Title> (<ID>)/OEBPS/` are not fetched again, so when Akamai answers `403` for a while (the script already retries those with a growing delay), wait a few minutes and run the same command again.

Log in through your browser and hand the session to the script as `cookies.json` (see [Usage](#usage) and `retrieve_cookies.py`). Only the `orm-jwt` and `orm-rt` cookies are needed. Do not send requests with an old browser `User-Agent`: O'Reilly invalidates the session as soon as it sees one.

---

## Overview:
  * [Requirements & Setup](#requirements--setup)
  * [Usage](#usage)
  * [Single Sign-On (SSO), Company, University Login](https://github.com/lorenzodifuccia/safaribooks/issues/150#issuecomment-555423085)
  * [Calibre EPUB conversion](https://github.com/lorenzodifuccia/safaribooks#calibre-epub-conversion)
  * [Example: Download *Test-Driven Development with Python, 2nd Edition*](#download-test-driven-development-with-python-2nd-edition)
  * [Example: Use or not the `--kindle` option](#use-or-not-the---kindle-option)

## Requirements & Setup:
First of all, it requires [`uv`](https://docs.astral.sh/uv/) to be installed (it will fetch a suitable Python, 3.12 or newer, by itself).  
```shell
$ git clone https://github.com/jbonadiman/safaribooks.git
Cloning into 'safaribooks'...

$ cd safaribooks/
$ uv sync
```  

Run the program with `uv run python safaribooks.py ...` (or activate `.venv` first).

The program depends on four **Python _3_** modules (`uv sync` installs them):
```python3
lxml>=4.1.1
requests>=2.20.0
pillow>=12.3.0
tinycss2>=1.5.1
```
Calibre's `ebook-polish` is optional: if it is on your `PATH` the script uses it at the end.
  
## Usage:
Log in to O'Reilly in your browser and save the session as `cookies.json` next to `safaribooks.py`
(run `uv run --with browser_cookie3 python retrieve_cookies.py`, or paste the output of
`cookieExtractor.js` from the browser console into the file). `--cred` and `--login` are disabled
for now, see [issue #358](https://github.com/lorenzodifuccia/safaribooks/issues/358).

Then replace the X-es with the ID of the book you want:

```shell
$ uv run python safaribooks.py XXXXXXXXXXXXX
```

The ID is the digits that you find in the URL of the book description page:  
`https://www.safaribooksonline.com/library/view/book-name/XXXXXXXXXXXXX/`  
Like: `https://www.safaribooksonline.com/library/view/test-driven-development-with/9781491958698/`  
  
#### Program options:
```shell
$ uv run python safaribooks.py --help
usage: safaribooks.py [--cred <EMAIL:PASS> | --login] [--no-cookies]
                      [--kindle] [--preserve-log] [--no-optimize-images]
                      [--no-optimize-css] [--help]
                      <BOOK ID>

Download and generate an EPUB of your favorite books from Safari Books Online.

positional arguments:
  <BOOK ID>             Book digits ID that you want to download. You can find
                        it in the URL (X-es):
                        `https://learning.oreilly.com/library/view/book-
                        name/XXXXXXXXXXXXX/`

optional arguments:
  --cred <EMAIL:PASS>   Credentials used to perform the auth login on Safari
                        Books Online. Es. ` --cred
                        "account_mail@mail.com:password01" `.
  --login               Prompt for credentials used to perform the auth login
                        on Safari Books Online.
  --no-cookies          Prevent your session data to be saved into
                        `cookies.json` file.
  --kindle              Add some CSS rules that block overflow on `table` and
                        `pre` elements. Use this option if you're going to
                        export the EPUB to E-Readers like Amazon Kindle.
  --preserve-log        Leave the `info_XXXXXXXXXXXXX.log` file even if there
                        isn't any error.
  --no-optimize-images  Skip converting images to JPEG, pruning unused images,
                        and running Calibre's `ebook-polish` (unused CSS
                        removal + lossless image compression) at the end of
                        the download.
  --no-optimize-css     Skip removing the `color` CSS property from
                        stylesheets and inline `style` attributes (kept to
                        avoid breaking E-Reader light/dark themes by default).
  --help                Show this help message.
```
  
The program reads your session from `cookies.json` (see [Usage](#usage)), and refreshes that file after a successful download so the next run keeps working until the session expires. This also covers **SSO** accounts: log in with your browser, then export the cookies with `retrieve_cookies.py` or `cookieExtractor.js` (see [`these steps`](https://github.com/lorenzodifuccia/safaribooks/issues/150#issuecomment-555423085)).  
  
Pay attention if you use a shared PC, because everyone that has access to your files can steal your session.  
`--no-cookies` only applies to the disabled `--cred` login, so it is rejected on its own.

You can configure proxies by setting on your system the environment variable `HTTPS_PROXY` or using the `USE_PROXY` directive into the script.

#### Calibre EPUB conversion
The EPUB is now the publisher's own, so converting it is no longer needed to get a valid book. It is still useful to change format, e.g. for Kindle, with `ebook-convert`:
```bash
$ ebook-convert "Books/<Title> (<ID>)/<ID>.epub" "Books/<Title> (<ID>)/<ID>.azw3"
```
If Calibre is installed, `ebook-polish` already runs at the end of the download (unless you pass `--no-optimize-images`).

The program also offers an option to ensure best compatibility for who wants to export the `EPUB` to E-Readers like Amazon Kindle: `--kindle`, it blocks overflow on `table` and `pre` elements (see [example](#use-or-not-the---kindle-option)).  
In this case, I suggest you to convert the `EPUB` to `AZW3` with Calibre or to `MOBI`, remember in this case to select `Ignore margins` in the conversion options:  
  
![Calibre IgnoreMargins](https://github.com/lorenzodifuccia/cloudflare/raw/master/Images/safaribooks/safaribooks_calibre_IgnoreMargins.png "Select Ignore margins")  
  
## Examples:
  * ## Download [Test-Driven Development with Python, 2nd Edition](https://www.safaribooksonline.com/library/view/test-driven-development-with/9781491958698/):  
    ```shell
    $ uv run python safaribooks.py 9781491958698
    ```  
    The script prints the book information (title, authors, publishers, ISBN, release date), then one
    progress bar per stage: documents, stylesheets, fonts, images, image optimization, and finally
    `Creating EPUB file...`. The result is `Books/<Title> (<ID>)/<ID>.epub`; open it with Calibre or any reader.  

  * ## Keep the book exactly as published (no optimization):
    ```shell
    $ uv run python safaribooks.py --no-optimize-images --no-optimize-css 9781491958698
    ```  
    Images stay as the publisher ships them, and the `color` property stays in the stylesheets.  

  * ## Use or not the `--kindle` option:
    ```bash
    $ uv run python safaribooks.py --kindle 9781491958698
    ```  
    On the right, the book created with `--kindle` option, on the left without (default):  
    
    ![NoKindle Option](https://github.com/lorenzodifuccia/cloudflare/raw/master/Images/safaribooks/safaribooks_example02_NoKindle.png "Version compare")  
    
---  
  
## Thanks!!
For any kind of problem, please don't hesitate to open an issue here on *GitHub*.  
  
*Lorenzo Di Fuccia*
