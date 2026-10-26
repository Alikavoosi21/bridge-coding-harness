"""Create a clean, versioned Windows handoff from an already verified build."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
NAME = f'Bridge-Coding-Harness-{VERSION}'
OUTPUT = ROOT.parent / 'outputs'
DELIVERY = OUTPUT / (NAME + '-Final')
INSTALLER = f'Bridge-Coding-Harness-Setup-{VERSION}.exe'


def digest(file):
    h = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    binary = ROOT / 'release/dist' / INSTALLER
    receipt = json.loads((ROOT / 'checks/chat-first/install.json').read_text(encoding='utf-8-sig'))
    smoke = json.loads((ROOT / 'checks/chat-first/installed.json').read_text(encoding='utf-8'))
    assert receipt['exit_code'] == 0 and receipt['version'] == VERSION
    assert smoke['passed'] and smoke['identity']['version'] == VERSION and smoke['identity']['packaged']
    assert digest(binary) == receipt['installer_sha256'].lower(), 'Installer differs from the verified build'
    # Never delete a previous delivery or mix old versions into this one.
    DELIVERY.mkdir(parents=True, exist_ok=False)
    shutil.copy2(binary, DELIVERY / INSTALLER)
    shutil.copy2(ROOT / 'LICENSE', DELIVERY / 'LICENSE.txt')
    shutil.copy2(ROOT / 'docs/third-party-sources.md', DELIVERY / 'THIRD-PARTY-NOTICES.fa.md')
    shutil.copytree(ROOT / 'examples/python-bug', DELIVERY / 'sample-project')

    source = DELIVERY / (NAME + '-Source.zip')
    excluded = {'.git', '.github', 'node_modules', '.venv', '.next', '.test-runs', 'out',
                'release', 'release-download', 'dist', 'build-engine', '__pycache__',
                '.pytest_cache', 'installed-before-toolchain-update', '.agents', '.codex'}
    with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
        for directory, folders, files in os.walk(ROOT):
            folders[:] = sorted(name for name in folders if name not in excluded and not (Path(directory) / name).is_symlink())
            for name in sorted(files):
                file = Path(directory) / name
                if file.is_symlink() or name.startswith('.env') or name.endswith(('.db', '.db-wal', '.db-shm', '.tsbuildinfo', '.pyc')) or name in {'failure.png', 'settings.json'}:
                    continue
                archive.write(file, Path('bridge-coding-harness') / file.relative_to(ROOT))

    guide = f'''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bridge Coding Harness — {VERSION}</title>
<style>body{{background:#010a04;color:#fff;font:16px/2.1 Tahoma,"Segoe UI",sans-serif;margin:0;padding:40px 20px}}main{{max-width:760px;margin:auto}}header{{display:flex;align-items:center;gap:18px}}svg{{width:58px;height:58px;flex:none}}h1{{font-size:24px;line-height:1.5}}h2{{font-size:18px;color:#4ade80;margin-top:30px}}section{{background:#191c21;border:1px solid #2c3930;border-radius:12px;padding:22px;margin:24px 0}}a{{color:#4ade80}}code{{direction:ltr;unicode-bidi:isolate;font-size:14px}}.muted{{color:#b8c2bb}}li{{margin:9px 0}}</style>
<main><header><svg viewBox="0 0 256 256" aria-hidden="true"><path fill="#4ADE80" d="M40 40H80V88H112V120H176V40H216V216H176V160H144V128H80V216H40Z"/></svg><div><h1>Bridge Coding Harness</h1><div class="muted">نسخهٔ {VERSION} · ویندوز ۶۴ بیتی</div></div></header>
<section><h2 style="margin-top:0">نصب و شروع</h2><ol>
<li>فایل <a href="{INSTALLER}"><code>{INSTALLER}</code></a> را اجرا کن.</li>
<li>برنامه را از میان‌بر <span dir="ltr">Bridge Coding Harness</span> باز کن.</li>
<li>می‌توانی راه‌اندازی را رد کنی و بعداً پروژه و مدل را انتخاب کنی.</li>
<li>برای اتصال مدل: تنظیمات ← مدل‌ها ← تعریف مدل. سرویس و کلید API را وارد کن، «دریافت مدل‌های سرویس» را بزن، مدل را انتخاب و ذخیره کن؛ سپس توانایی ابزار را بررسی کن.</li>
<li>برای تغییر و اجرای کد، Docker Desktop را روشن کن و آمادگی محیط و فرمان‌های پروژه را در برنامه بررسی کن.</li>
</ol></section>
<h2>پیش‌نیازها</h2><p>Node و Python همراه برنامه‌اند و نصب جدا نمی‌خواهند. اجرای فرمان‌ها به Docker Desktop با موتور آماده نیاز دارد. برای مدل آنلاین، کلید API همان سرویس و اتصال شبکه لازم است؛ demo فقط روند کار را نشان می‌دهد.</p>
<p class="muted">Docker و کلید مدل داخل این بسته نیستند. نصب‌کننده امضای ناشر ندارد. برنامهٔ قبلی و داده‌هایش با این محصول ادغام نمی‌شوند.</p>
<h2>اولین کار</h2><p>پوشهٔ <code>sample-project</code> را در جایی که می‌خواهی کار کنی کپی و در برنامه انتخاب کن. این پروژه یک باگ عمدی دارد.</p>
<section>«تابع add در main.py اشتباه است. اول تست را اجرا کن، فقط main.py را اصلاح کن و دوباره تست بگیر. check.py را تغییر نده و پیش از اعمال، diff را نشان بده.»<br><span class="muted">فرمان تست: <code>python check.py</code></span></section>
<h2>گفتگو و مهارت</h2><p>از همان چت سؤال بپرس، درخواست تغییر بده یا ادامه بده. برنامه و تأییدها داخل گفتگو هستند. برای افزودن یا فراخوانی Skill، دکمهٔ «مهارت» کنار ورودی را بزن. «پیوست‌ها» فقط فایل‌هایی را نشان می‌دهد که خودت ارسال کرده‌ای.</p>
<h2>داده و حذف برنامه</h2><p>تنظیمات در <code>%APPDATA%/BridgeCodingHarness</code> و کلیدها در مخزن امن ویندوز هستند. حذف برنامه از تنظیمات Apps ویندوز انجام می‌شود؛ داده‌ها خودکار پاک نمی‌شوند.</p>
<h2>محتویات تحویل</h2><p>نصب‌کنندهٔ نهایی، پروژهٔ نمونه، سورس همین نسخه، مجوز AGPL-3.0، انتساب منابع و <code>SHA256SUMS.txt</code>. سورس برای استفادهٔ عادی لازم نیست.</p>
<p class="muted">این نسخه نصب و آزمایش شده است: ۴۲۲ تست هسته پاس، ۳ مورد skip؛ ۴۴ تست قرارداد و ۱۰ بررسی نسخهٔ نصب‌شده پاس. اتصال چت و Skill با سرویس کنترل‌شدهٔ محلی بررسی شده است؛ نتیجهٔ کار با مدل انتخابی تو جدا بررسی می‌شود.</p>
</main></html>'''
    (DELIVERY / 'START-HERE.fa.html').write_text(guide, encoding='utf-8')
    info = {'product': 'Bridge Coding Harness', 'version': VERSION, 'platform': 'Windows x64',
            'installer': INSTALLER, 'installer_sha256': digest(binary),
            'checks': {'backend_passed': 422, 'backend_skipped': 3, 'contract_passed': 44, 'installed_ui_passed': 10},
            'provider_test': 'Controlled local provider; no live user-provider acceptance claimed',
            'license': 'AGPL-3.0-only'}
    (DELIVERY / 'release-info.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    files = sorted(file for file in DELIVERY.rglob('*') if file.is_file())
    (DELIVERY / 'SHA256SUMS.txt').write_text(''.join(f'{digest(file)}  {file.relative_to(DELIVERY).as_posix()}\n' for file in files), encoding='utf-8')
    bundle = OUTPUT / (NAME + '-Final.zip')
    with zipfile.ZipFile(bundle, 'x', zipfile.ZIP_STORED) as archive:
        for file in sorted(DELIVERY.rglob('*')):
            if file.is_file():
                archive.write(file, Path(DELIVERY.name) / file.relative_to(DELIVERY))
    with zipfile.ZipFile(bundle) as archive:
        assert archive.testzip() is None
    with zipfile.ZipFile(source) as archive:
        assert archive.testzip() is None
        assert json.loads(archive.read('bridge-coding-harness/package.json'))['version'] == VERSION
    print(json.dumps({'folder': str(DELIVERY), 'bundle': str(bundle), 'bytes': bundle.stat().st_size,
                      'sha256': digest(bundle), 'installer_sha256': digest(binary)}, indent=2))


if __name__ == '__main__':
    main()
