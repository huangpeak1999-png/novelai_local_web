"""Optional browser smoke test against an explicitly enabled loopback Mock app.

Start Flask with comfyui.mock.example.json and build the frontend first.
Requires an existing Playwright Python package and Chromium (not app dependencies).
Run: python scripts/comfyui_browser_smoke.py
This uses isolated browser contexts and writes screenshots only under /tmp.
"""
from playwright.sync_api import sync_playwright
import json
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:5000/comfycomic')
    page.get_by_text('Mock 测试数据：未使用 GPU 或真实模型。',exact=True).wait_for()
    page.get_by_role('button',name='Templates',exact=True).click()
    page.get_by_text('Two vertical',exact=True).click()
    print('CONFIRM',page.get_by_role('dialog').inner_text())
    page.get_by_role('dialog').get_by_role('button',name='Confirm',exact=True).click()
    page.locator('polygon[data-panel]').nth(1).wait_for()
    panels=page.locator('polygon[data-panel]')
    ids=[panels.nth(i).get_attribute('data-panel') for i in range(panels.count())]
    print('PANELS',ids)
    panels.first.click()
    page.get_by_label('正向提示词',exact=False).first.fill('A mock comic test')
    with page.expect_response(lambda r:'/api/comfyui/jobs' in r.url and r.request.method=='POST') as response:
        page.get_by_role('button',name='ComfyUI 生成',exact=True).click()
    job=response.value.json()
    print('SUBMITTED',json.dumps(job,ensure_ascii=False))
    panels.nth(1).click()
    page.get_by_text('图片已回填提交时的画格。',exact=True).wait_for(timeout=15000)
    data=page.evaluate('''() => new Promise((resolve,reject)=>{const request=indexedDB.open('novelai-comic-workspace',1);request.onsuccess=()=>{const q=request.result.transaction('drafts').objectStore('drafts').get('current');q.onsuccess=()=>resolve(q.result.page);q.onerror=reject;};request.onerror=reject;})''')
    assert data['id']==job['target']['pageId']
    assert data['panels'][0]['id']==job['target']['panelId']
    assert data['panels'][0]['image']['dataUrl'].startswith('data:image/png;base64,')
    assert data['panels'][1]['image'] is None
    assert page.get_by_alt_text('Mock 测试图像，非 GPU 生成').count()==1
    assert not errors, errors
    page.screenshot(path='/tmp/comfy-desktop-result.png')
    print('DESKTOP_PASS',json.dumps({'bound_panel':ids[0],'current_panel':ids[1],'image_size':len(data['panels'][0]['image']['dataUrl']),'errors':errors}))
    # Fresh Android-sized context, same loopback-only deployment, no NovelAI login.
    mobile=browser.new_context(viewport={'width':393,'height':851},is_mobile=True,has_touch=True,device_scale_factor=1)
    phone=mobile.new_page()
    phone.on('pageerror', lambda error: errors.append(str(error)))
    phone.goto('http://127.0.0.1:5000/comfycomic')
    phone.get_by_text('Mock 测试数据：未使用 GPU 或真实模型。',exact=True).wait_for()
    phone.get_by_role('button',name='ComfyUI 生成',exact=True).wait_for()
    phone.locator('polygon[data-panel]').first.tap()
    phone.get_by_label('正向提示词',exact=False).first.fill('Mobile mock test')
    phone.get_by_role('button',name='ComfyUI 生成',exact=True).tap()
    phone.get_by_text('图片已回填提交时的画格。',exact=True).wait_for(timeout=15000)
    assert phone.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    phone.screenshot(path='/tmp/comfy-mobile-result.png')
    assert not errors, errors
    print('MOBILE_PASS touch selection, generation, preview, bound fill; no horizontal page overflow')
    browser.close()
