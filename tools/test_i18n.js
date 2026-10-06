/*
 * Smoke test for the Chinese build: runs the built rise.js inside jsdom and
 * checks (a) it initialises without throwing, (b) the panels render in Chinese,
 * (c) the pixel screen-reader recognises a Chinese "选项" / "游戏菜单" title.
 *
 * The synthetic frame is drawn with Minecraft's own unihex geometry: oversample
 * 2 (a 16x16 glyph is 8x8 on screen and advances width/2 + 1 = 9) and GL_NEAREST
 * sampling of the atlas with the 0.01-texel UV inset.
 *
 * Run:  NODE_PATH=<jsdom> node tools/test_i18n.js
 * (`tools/i18n_build.py --check` prints where the built payload lives; by
 * default this reads /tmp/rise_built.js.)
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.dirname(__dirname);
const GLYPHS_ZH = JSON.parse(fs.readFileSync(path.join(ROOT, 'theme_extra/glyphs_zh.json'), 'utf8'));
const GLYPHS_EN = JSON.parse(fs.readFileSync(path.join(ROOT, 'theme_extra/glyphs.json'), 'utf8'));
const RISE = fs.readFileSync(process.env.RISE_JS || '/tmp/rise_built.js', 'utf8');

let fails = 0;
function ok(cond, msg) {
	console.log((cond ? '  ok   ' : '  FAIL ') + msg);
	if (!cond) fails++;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- glyph render
// independent re-implementation of MC's unihex downsample
function sampleIndices(p) {
	const out = [];
	for (let i = 0; i < 8; i++) out.push(Math.floor(0.01 + (i + 0.5 - p) * 15.98 / 8));
	return out;
}
function renderGlyph(ch, phase) {
	const g = GLYPHS_ZH[ch];
	if (!g) throw new Error('no glyph for ' + ch);
	if (g[0] === 8) return { w: g[2], adv: g[2] + 1, px: (x, y) => (g[1][y] >> x) & 1 };
	const idx = sampleIndices(phase);
	return { w: 8, adv: 9, px: (x, y) => (g[1][idx[y]] >> (15 - idx[x])) & 1 };
}
function textWidth(text, phase) {
	let w = 0;
	for (const ch of text) w += renderGlyph(ch, phase).adv;
	return w;
}

// ---------------------------------------------------------------- synthetic GL
const W = 1280, H = 720;
const makeFb = () => {
	const fb = new Uint8Array(W * H * 4);
	for (let i = 0; i < fb.length; i += 4) { fb[i] = fb[i + 1] = fb[i + 2] = 28; fb[i + 3] = 255; }
	return fb;
};
function setGui(fb, gx, gy, s, v) {
	const fx = gx * s + (s >> 1), fy = gy * s + (s >> 1);
	for (let dy = 0; dy < s; dy++) for (let dx = 0; dx < s; dx++) {
		const px = fx + dx, py = fy + dy;
		if (px < 0 || py < 0 || px >= W || py >= H) continue;
		const i = ((H - 1 - py) * W + px) * 4; // GL buffer is bottom-up
		fb[i] = fb[i + 1] = fb[i + 2] = v; fb[i + 3] = 255;
	}
}
function drawText(fb, text, gx, gy, s, phase) {
	let x = gx;
	for (const ch of text) {
		const g = renderGlyph(ch, phase);
		for (let r = 0; r < 8; r++) for (let c = 0; c < g.w; c++) if (g.px(c, r)) setGui(fb, x + c, gy + r, s, 255);
		x += g.adv;
	}
}

// ---------------------------------------------------------------- run rise.js
const dom = new JSDOM('<!doctype html><html><head></head><body><div id="game_frame"><canvas></canvas></div></body></html>',
	{ url: 'https://example.test/', pretendToBeVisual: true, runScripts: 'outside-only' });
const win = dom.window;
for (const k of ['Response', 'Blob', 'DecompressionStream', 'CompressionStream', 'TextDecoder', 'TextEncoder', 'Event', 'KeyboardEvent', 'fetch']) {
	if (globalThis[k] && !win[k]) win[k] = globalThis[k];
}
win.eaglercraftXOpts = { worldsDB: 'worlds' };
class FakeGL2 { }                       // rise.js wraps this to hook presented frames
FakeGL2.prototype.bindFramebuffer = function () { };
FakeGL2.prototype.drawArrays = function () { };
win.WebGL2RenderingContext = FakeGL2;

(async () => {
	console.log('— load');
	try {
		win.eval(RISE);
		ok(!!win.rise, 'rise.js initialised (window.rise present)');
	} catch (e) {
		ok(false, 'rise.js threw: ' + e.message + '\n' + (e.stack || ''));
		process.exit(1);
	}
	await sleep(1200); // the host element is mounted on a 1s interval

	const root = win.document.getElementById('rise-client').shadowRoot;
	ok(!!root, 'shadow root mounted');
	ok(root.querySelector('[data-b=video]').textContent === '视频设置…', 'overlay button says 视频设置…');
	ok(root.querySelector('[data-b=mods]').textContent === '模组', 'overlay button says 模组');

	// ---------------------------------------------------------------- panels
	console.log('— panels');
	try {
		await win.rise.open('mods');
		const tabs = [...root.querySelectorAll('.tab')].map((t) => t.textContent);
		ok(tabs.join('|') === 'HUD|玩法|红石|卡顿|杂项|皮肤', 'mods tabs: ' + tabs.join('|'));
		const txt = root.querySelector('.scrim').textContent;
		ok(txt.includes('按键显示'), 'mods panel has 按键显示 (Keystrokes)');
		ok(txt.includes('勾选方框即可开启模组'), 'mods hint translated');
		[...root.querySelectorAll('.tab')].find((t) => t.textContent === '卡顿').onclick();
		ok(root.querySelector('.scrim').textContent.includes('清理掉落物'), 'Lag tab has 清理掉落物 (Clear Lag)');
	} catch (e) {
		ok(false, 'mods panel threw: ' + e.message);
	}
	win.rise.close();
	await sleep(300); // the old scrim is only removed after its fade-out
	try {
		await win.rise.open('video');
		const tabs = [...root.querySelectorAll('.tab')].map((t) => t.textContent);
		ok(tabs.join('|') === '常规|画质|性能|高级', 'video tabs: ' + tabs.join('|'));
		const txt = root.querySelector('.scrim').textContent;
		ok(txt.includes('渲染距离'), 'video panel has 渲染距离');
		ok(txt.includes('应用'), 'video panel has the 应用 button');
		[...root.querySelectorAll('.tab')].find((t) => t.textContent === '高级').onclick();
		const adv = root.querySelector('.scrim').textContent;
		ok(adv.includes('语言') && adv.includes('简体中文'), 'language row defaults to 简体中文');
	} catch (e) {
		ok(false, 'video panel threw: ' + e.message);
	}
	win.rise.close();
	await sleep(300);

	// ---------------------------------------------------------------- detection
	console.log('— screen reader (Chinese)');
	win.__eaglerGameReady = true;
	const s = 3, gw = Math.floor(W / s);
	const proto = FakeGL2.prototype;
	const gl = new FakeGL2();
	gl.drawingBufferWidth = W; gl.drawingBufferHeight = H;
	gl.getParameter = () => null;
	gl.RGBA = 0x1908; gl.UNSIGNED_BYTE = 0x1401;
	function runFrame(fb) {
		gl.readPixels = (x, y, w, h, fmt, type, buf) => {
			for (let row = 0; row < h; row++) {
				const src = ((y + row) * W + x) * 4;
				buf.set(fb.subarray(src, src + w * 4), row * w * 4);
			}
		};
		proto.bindFramebuffer.call(gl, 0x8CA9, null); // marks the default framebuffer
		proto.drawArrays.call(gl, 0, 0, 3);           // "presents" the frame
	}
	const centred = (text, phase) => Math.floor(gw / 2) - Math.floor(textWidth(text, phase) / 2);

	for (const phase of [0, 0.5]) {
		const fb = makeFb();
		drawText(fb, '选项', centred('选项', phase), 15, s, phase);
		runFrame(fb);
		ok(win.rise.screen.name === 'options', 'phase ' + phase + ': 选项 detected as the options screen (got ' + win.rise.screen.name + ')');
	}

	runFrame(makeFb());
	ok(win.rise.screen.name === null, 'empty frame reports no screen (got ' + win.rise.screen.name + ')');

	{
		const phase = 0, fb = makeFb();
		drawText(fb, '游戏菜单', centred('游戏菜单', phase), 15, s, phase);
		drawText(fb, '保存并退回到标题屏幕', centred('保存并退回到标题屏幕', phase), 150, s, phase);
		runFrame(fb);
		ok(win.rise.screen.name === 'pause', '游戏菜单 detected as the pause menu (got ' + win.rise.screen.name + ')');
		const r = win.rise.screen.rects.mods;
		ok(!!r && r.y > 150 && r.y < 200, 'Mods button lands under the last button: ' + JSON.stringify(r));
	}

	console.log(fails ? '\n' + fails + ' FAILED' : '\n' + (await englishPass()));
	process.exit(fails ? 1 : 0);
})();

// ---------------------------------------------------------------- English build
// Same script with the language pinned to English: the panels must fall back to
// English and the reader must still recognise the vanilla titles. (The Rise UI
// defaults to Chinese, so this has to be an explicit choice.)
async function englishPass() {
	console.log('— English regression');
	const d2 = new JSDOM('<!doctype html><html><head></head><body><div id="game_frame"><canvas></canvas></div></body></html>',
		{ url: 'https://example.test/', pretendToBeVisual: true, runScripts: 'outside-only' });
	const w2 = d2.window;
	for (const k of ['Response', 'Blob', 'DecompressionStream', 'CompressionStream', 'TextDecoder', 'TextEncoder', 'Event', 'KeyboardEvent', 'fetch']) {
		if (globalThis[k] && !w2[k]) w2[k] = globalThis[k];
	}
	w2.localStorage.setItem('rise.gamelang', JSON.stringify('en'));
	w2.localStorage.setItem('rise.config', JSON.stringify({ lang: 'en' }));
	w2.eaglercraftXOpts = { worldsDB: 'worlds' };
	class GL2b { }
	GL2b.prototype.bindFramebuffer = function () { };
	GL2b.prototype.drawArrays = function () { };
	w2.WebGL2RenderingContext = GL2b;
	w2.eval(RISE);
	await sleep(1200);
	const r2 = w2.document.getElementById('rise-client').shadowRoot;
	ok(r2.querySelector('[data-b=video]').textContent === 'Video Settings...', 'overlay button stays English');
	await w2.rise.open('mods');
	const tabs = [...r2.querySelectorAll('.tab')].map((t) => t.textContent);
	ok(tabs.join('|') === 'HUD|Gameplay|Redstone|Lag|Misc|Skins', 'mods tabs stay English: ' + tabs.join('|'));
	w2.rise.close();
	await sleep(300);

	w2.__eaglerGameReady = true;
	const s = 3, gw = Math.floor(W / s);
	const gl = new GL2b();
	gl.drawingBufferWidth = W; gl.drawingBufferHeight = H;
	gl.getParameter = () => null;
	function frame(fb) {
		gl.readPixels = (x, y, w, h, fmt, type, buf) => {
			for (let row = 0; row < h; row++) {
				const src = ((y + row) * W + x) * 4;
				buf.set(fb.subarray(src, src + w * 4), row * w * 4);
			}
		};
		GL2b.prototype.bindFramebuffer.call(gl, 0x8CA9, null);
		GL2b.prototype.drawArrays.call(gl, 0, 0, 3);
	}
	const fb = makeFb();
	let x = Math.floor(gw / 2) - Math.floor(asciiWidth('Options') / 2);
	for (const ch of 'Options') {
		const g = GLYPHS_EN[ch];
		for (let row = 0; row < 8; row++) for (let c = 0; c < g[0]; c++) if ((g[1][row] >> c) & 1) setGui(fb, x + c, 15 + row, s, 255);
		x += g[0] + 1;
	}
	frame(fb);
	ok(w2.rise.screen.name === 'options', 'Options detected as the options screen (got ' + w2.rise.screen.name + ')');
	return fails ? fails + ' FAILED' : 'all checks passed';
}
function asciiWidth(text) {
	let w = 0;
	for (const ch of text) w += GLYPHS_EN[ch][0] + 1;
	return w;
}
