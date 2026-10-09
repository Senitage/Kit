/* Kit's 3D face: the model Dan designed in Blender, acted out live.

   The brain serves this page, the model and its pack (kit.face.serve), and the
   page reloads itself whenever any of them changes, so a rebuilt model or a
   change to how Kit moves reaches every screen without a new desk app.

   Whoever shows the page drives it through window.kit:
     kit.setEmotion('happy')   ease into a mood from the pack (and its move)
     kit.play('nod')           one of Kit's gestures (kit.reply), or a clip name
     kit.setState('sleeping')  idle, sleeping, listening, thinking, speaking, working, offline
     kit.lookAt(x, y)          look toward a point, -1..1 each way, y down
     kit.frame()               draw now and return the picture as a PNG data URL
                               (the desk app copies these into its window)
     kit.setDials(a, v)        the mood dials: arousal 0..1 (livelier moves and
                               blinks), valence -1..1 (more or less blush)
     kit.show({...})           a show from the brain (kit.shows): weather, time, date,
                               or any show in the pack by name ({kind: 'dream'})
   Asleep, he shows the pack's sleep show and now and then drifts into its dream.
   Calls made before the model has loaded are kept and played once it has.

   Page options (query string): app=desk (whose look to draw), character=<preset>,
   bg=transparent|<css colour>, bloom=0|1.

   Based on the Blender thread's kit_tuner (three.js r147): mood blending, blink,
   gaze, talk, energy-scaled idle motion, gestures, and weather shows with props. */
(function () {
  'use strict';
  var params = new URLSearchParams(location.search);
  var APP = params.get('app') || 'desk';
  var CHARACTER = params.get('character') || '';
  var BG = params.get('bg') || 'transparent';
  var POLL_MS = 4000;
  var SHOW_SECONDS = 8;
  // Asleep: dream for DREAM_SECONDS every DREAM_EVERY seconds, the first after DREAM_AFTER.
  var DREAM_AFTER = 60, DREAM_EVERY = 180, DREAM_SECONDS = 25;
  // Seven-segment digits (segments a..g) for the model's clock and thermometer.
  var SEGMENTS = ['abcdef', 'bc', 'abdeg', 'abcdg', 'bcfg', 'acdfg', 'acdefg', 'abc', 'abcdefg', 'abcdfg'];
  var OFFLINE_COLOUR = '#8c96a0';
  var $ = function (id) { return document.getElementById(id); };
  function say(text) { $('msg').textContent = text || ''; }
  function query(extra) {
    var q = new URLSearchParams({ app: APP });
    if (CHARACTER) q.set('character', CHARACTER);
    return q.toString() + (extra || '');
  }

  // ---- what the host has asked for (kept across a reload) ----
  var want = { emotion: 'neutral', state: 'idle', look: null, show: null };
  try { Object.assign(want, JSON.parse(sessionStorage.getItem('kit-face') || '{}')); } catch (e) {}
  var queue = [];
  var dials = { arousal: 0.5, valence: 0 };  // as Glow's rig reads them (kit.face.rig)
  var ready = false;
  function remember() {
    try { sessionStorage.setItem('kit-face', JSON.stringify({ emotion: want.emotion, state: want.state })); } catch (e) {}
  }

  var kit = window.kit = {
    setEmotion: function (name) { want.emotion = name || 'neutral'; remember(); if (ready) setMood(want.emotion); },
    play: function (gesture) { if (ready) playGesture(gesture); else queue.push(['play', gesture]); },
    setState: function (state) {
      want.state = state || 'idle';
      if (want.state === 'sleeping' || want.state === 'offline') endShow(true);
      else if (show && (pack.weather || {})[show.kind] && pack.weather[show.kind].asleep) endShow(true);  // woken from a dream
      remember();
    },
    lookAt: function (x, y) { want.look = { x: +x || 0, y: +y || 0, until: now() + 3 }; },
    setDials: function (arousal, valence) {
      dials.arousal = Math.max(0, Math.min(1, +arousal || 0));
      dials.valence = Math.max(-1, Math.min(1, +valence || 0));
    },
    show: function (what) { if (ready) startShow(what); else queue.push(['show', what]); },
    // Drawn and read in one go, so the picture is always whole.
    frame: function () { if (!ready) return null; draw(); return renderer.domElement.toDataURL('image/png'); },
    info: null,
    ready: false,  // true once Kit's model is on screen (the desk app shows Glow until then)
  };

  // ---- the scene ----
  var info, pack, moods, gestures, tuning;
  var baseZ = 6.4, renderer, scene, camera, composer, bloom, hemi, shadow, pivot, headBone, glowMat;
  var mixer, propMixer, currentAction = null, clips = {}, faceMeshes = [];
  // Show props: each node once (sleep and dream share some), and each show's nodes.
  var props = {}, showProps = {};
  var digitCtx, digitTex, digitPlane, segs = {}, hasSegments = false;
  var mode = '', asleepSince = null;
  var cur = {}, target = {}, gaze = { x: 0, y: 0 }, curColour = new THREE.Color(), tmpC = new THREE.Color();
  var curTilt = 0, curEnergy = 0.45, glowScale = 1, flash = 0;
  var blinkT = 0, nextBlink = 2, pulse = null, show = null, lastDigits = '';
  var clock = new THREE.Clock(), tmpV = new THREE.Vector3();
  function now() { return clock.elapsedTime; }

  function mood(name) { return moods[name] || moods.neutral || { shape_keys: {}, glow_colour: '#4dffc0', energy: 0.45, lean_degrees: 0 }; }

  function init() {
    var transparent = BG === 'transparent';
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: transparent, premultipliedAlpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputEncoding = THREE.sRGBEncoding;
    if (transparent) renderer.setClearColor(0x000000, 0);
    $('kit').appendChild(renderer.domElement);
    scene = new THREE.Scene();
    if (!transparent) { document.body.style.background = BG; scene.background = new THREE.Color(BG).convertSRGBToLinear(); }
    var pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new THREE.RoomEnvironment(), 0.04).texture;
    camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
    camera.position.set(0, 0.25, 6.4);
    camera.lookAt(0, 0.05, 0);
    hemi = new THREE.HemisphereLight(0xdfe8f5, 0x20242c, 0.2); scene.add(hemi);
    var key = new THREE.DirectionalLight(0xffffff, 0.6); key.position.set(-3, 4, 4); scene.add(key);
    var rim = new THREE.DirectionalLight(0xcfe0ff, 0.6); rim.position.set(3, 2, -4); scene.add(rim);

    // Bloom makes the glow bleed beautifully but paints over a see-through window,
    // so it's on for pages with a background and off over the desktop.
    var useBloom = params.get('bloom') ? params.get('bloom') === '1' : !transparent;
    if (useBloom) {
      composer = new THREE.EffectComposer(renderer);
      composer.addPass(new THREE.RenderPass(scene, camera));
      bloom = new THREE.UnrealBloomPass(new THREE.Vector2(512, 512), 0.5, 0.5, 0.85);
      composer.addPass(bloom);
      composer.addPass(new THREE.ShaderPass(THREE.GammaCorrectionShader));
    }

    // a soft contact shadow under Kit
    var c = document.createElement('canvas'); c.width = c.height = 128;
    var g = c.getContext('2d'), grad = g.createRadialGradient(64, 64, 4, 64, 64, 64);
    grad.addColorStop(0, 'rgba(0,0,0,0.5)'); grad.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
    shadow = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 1.0),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
    shadow.rotation.x = -Math.PI / 2; shadow.position.y = -0.9; scene.add(shadow);

    resize();
    window.addEventListener('resize', resize);
    // Following the pointer inside the page too (home_app); the desk sends lookAt.
    window.addEventListener('pointermove', function (e) {
      kit.lookAt((e.clientX / innerWidth) * 2 - 1, (e.clientY / innerHeight) * 2 - 1);
    });
    new THREE.GLTFLoader().load(info.model, onModel, undefined, function (err) {
      say("Kit's model didn't load: " + (err && err.message || err));
    });
  }

  function onModel(gltf) {
    var model = gltf.scene;
    pivot = new THREE.Group(); pivot.position.y = -0.84; scene.add(pivot);
    model.position.y = 0.84; pivot.add(model);
    model.traverse(function (o) {
      if (o.isMesh && o.morphTargetDictionary) faceMeshes.push(o);
      if (o.isMesh) o.frustumCulled = false;
      var m = o.material;
      if (!m) return;
      if (m.name === 'Mint glow') glowMat = m;
      if (m.name === 'Shell') m.envMapIntensity = 0.12;
      if (/cloud/i.test(m.name)) m.envMapIntensity = 0.2;
      if (m.name === 'Rain') { m.color.set(0x000000); m.emissiveIntensity = 0.55; }
      if (m.name === 'Blush') { m.color.set(0x000000); m.emissiveIntensity = 0.45; }
    });
    headBone = model.getObjectByName(info.look.head_bone || 'head');
    model.updateMatrixWorld(true);
    // Weather props live in the world, not on Kit, so they don't sway with him.
    propMixer = new THREE.AnimationMixer(scene);
    Object.keys(pack.weather || {}).forEach(function (kind) {
      var w = pack.weather[kind];
      showProps[kind] = (w.props_groups || (w.props_group ? [w.props_group] : [])).filter(function (name) {
        if (props[name]) return true;
        var node = model.getObjectByName(name);
        if (!node) return false;
        scene.attach(node); node.visible = false;
        props[name] = { node: node, clips: [], shown: 0, base: node.scale.clone() };
        return true;
      });
    });
    // The clock and thermometer digits on his face, hidden until a show needs them.
    model.traverse(function (o) {
      if (/^(Time|Temp)_/.test(o.name)) { segs[o.name] = o; o.visible = false; }
    });
    hasSegments = !!segs.Time_D0_a;
    var dict = (faceMeshes[0] && faceMeshes[0].morphTargetDictionary) || {};
    Object.keys(dict).forEach(function (name) { cur[name] = 0; });
    mixer = new THREE.AnimationMixer(model);
    gltf.animations.forEach(function (clip) { clips[clip.name] = clip; });
    Object.keys(props).forEach(function (name) {
      var grp = props[name], inside = new Set();
      grp.node.traverse(function (o) { inside.add(THREE.PropertyBinding.sanitizeNodeName(o.name)); });
      gltf.animations.forEach(function (clip) {
        if (clip.tracks.some(function (t) { return inside.has(t.name.split('.')[0]); })) {
          grp.clips.push(propMixer.clipAction(clip).setLoop(THREE.LoopRepeat, Infinity));
        }
      });
    });

    // A display riding on his head for the time, the date and the temperature.
    var dc = document.createElement('canvas'); dc.width = 512; dc.height = 256;
    digitCtx = dc.getContext('2d'); digitTex = new THREE.CanvasTexture(dc); digitTex.encoding = THREE.sRGBEncoding;
    digitPlane = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.75),
      new THREE.MeshBasicMaterial({ map: digitTex, transparent: true, depthWrite: false, toneMapped: false }));
    digitPlane.position.set(0, -0.02, 0.5);
    scene.add(digitPlane); digitPlane.updateMatrixWorld(true);
    (headBone || model).attach(digitPlane);
    digitPlane.visible = false;

    curColour.set(mood(want.emotion).glow_colour || '#4dffc0').convertSRGBToLinear();
    say('');
    ready = kit.ready = true;
    setMood(want.emotion, true);
    queue.splice(0).forEach(function (call) { kit[call[0]](call[1]); });
    if (!currentAction) playClip('bounce');
    requestAnimationFrame(tick);
  }

  // ---- what Kit does ----
  function setMood(name, quiet) {
    var changed = name !== state.mood;
    state.mood = moods[name] ? name : 'neutral';
    var move = mood(state.mood).move;
    if (!quiet && changed && tuning.move_on_mood_change !== false && move && !show) playClip(move);
  }
  var state = { mood: 'neutral' };

  function playClip(name, loop) {
    if (!mixer || !clips[name]) return false;
    var action = mixer.clipAction(clips[name]);
    action.reset();
    action.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, loop ? Infinity : 1);
    action.clampWhenFinished = false;
    if (currentAction && currentAction !== action) currentAction.crossFadeTo(action, loop ? 0.35 : 0.15, false);
    action.play(); currentAction = action;
    return true;
  }

  /* One of Kit's gestures: the clip the sheet maps it to, plus a face pulse (a wink,
     a laugh) eased in and out over the clip. A bare clip name works too. */
  function playGesture(name) {
    if (!name || name === 'none' || show) return;
    var g = gestures[name] || { clip: name };
    playClip(g.clip);
    if (g.face) {
      var seconds = clips[g.clip] ? Math.max(0.6, Math.min(clips[g.clip].duration, 2.2)) : 1.0;
      pulse = { face: g.face, start: now(), seconds: seconds };
    }
  }

  /* A show from the brain (kit.shows): weather brings its props and a mood, and the
     temperature on his face; time and date turn his face into a clock. */
  function startShow(what) {
    if (!what || !what.kind) return;
    endShow(true);
    var shows = pack.weather || {};
    var kind = what.kind === 'weather' ? weatherKind(what.sky || '') : shows[what.kind] ? what.kind : '';
    show = { what: what, kind: kind, until: now() + (+what.seconds || SHOW_SECONDS), digits: false };
    var w = kind && shows[kind];
    if (w) {
      state.showMood = w.mood;
      show.face = w.shape_keys || {};
      playClip(w.move, !!w.loop_move);
      // after the props have popped in, his eyes show the temperature
      show.digitsAt = now() + 2.5;
    } else {
      show.digitsAt = now();
    }
  }
  /* Which of the pack's weather shows a sky from the brain (kit.shows) brings: its
     own name when the pack has it (rain, storm, sunny, wind, fog, hot), else the
     nearest one an older pack has, else none (just the temperature). */
  var SKY_SHOWS = {
    storm: ['storm', 'rain'], rain: ['rain'], snow: ['rain'], sun: ['sunny'],
    part_cloud: ['sunny'], hot: ['hot', 'sunny'], wind: ['wind'], fog: ['fog'],
  };
  function weatherKind(sky) {
    var have = pack.weather || {};
    var choices = SKY_SHOWS[sky] || [sky];
    for (var i = 0; i < choices.length; i++) if (have[choices[i]]) return choices[i];
    return '';
  }
  function endShow(quiet) {
    if (!show) return;
    state.showMood = null;
    show = null;
    if (digitPlane) digitPlane.visible = false;
    if (!quiet) playClip('bounce');
  }

  function drawDigits(text, small) {
    var key = text + '|' + small;
    if (key === lastDigits) return;
    lastDigits = key;
    var g = digitCtx; g.clearRect(0, 0, 512, 256);
    g.fillStyle = '#ffffff'; g.textAlign = 'center'; g.textBaseline = 'middle';
    var big = text.length > 5 ? 110 : 150;
    g.font = '600 ' + big + 'px "Segoe UI", system-ui, sans-serif';
    g.fillText(text, 256, small ? 115 : 135);
    if (small) { g.font = '600 52px "Segoe UI", system-ui, sans-serif'; g.fillText(small, 256, 215); }
    digitTex.needsUpdate = true;
  }

  /* Light a number on the model's own seven-segment digits: the clock (H:MM, the
     colon blinking) or the thermometer (two digits, a minus, the degree sign). */
  function lightDigit(prefix, ch) {
    var on = ch === '-' ? 'g' : ch >= '0' && ch <= '9' ? SEGMENTS[+ch] : '';
    'abcdefg'.split('').forEach(function (seg) {
      var node = segs[prefix + '_' + seg];
      if (node) node.visible = on.indexOf(seg) >= 0;
    });
  }
  function hideSegments() {
    Object.keys(segs).forEach(function (name) { segs[name].visible = false; });
  }
  function showSegments(what, t) {
    hideSegments();
    if (!hasSegments) return false;
    var text = String(what.text || '');
    if (what.kind === 'time') {
      var hm = /^(\d{1,2}):(\d{2})$/.exec(text);
      if (!hm) return false;
      var hh = ('  ' + hm[1]).slice(-2), mm = hm[2];
      [hh[0], hh[1], mm[0], mm[1]].forEach(function (ch, i) { lightDigit('Time_D' + i, ch); });
      if (segs.Time_Colon) segs.Time_Colon.visible = t % 1 < 0.6;
      return true;
    }
    if (what.kind === 'weather') {
      var deg = /^(-?\d{1,3})/.exec(text);
      if (!deg) return false;
      var n = Math.max(-99, Math.min(99, +deg[1])), abs = String(Math.abs(n));
      var d0 = abs.length > 1 ? abs[0] : n < 0 ? '-' : ' ', d1 = abs[abs.length - 1];
      lightDigit('Temp_D0', d0); lightDigit('Temp_D1', d1);
      if (segs.Temp_Minus) segs.Temp_Minus.visible = n <= -10;
      if (segs.Temp_Deg) segs.Temp_Deg.visible = true;
      if (segs.Temp_C) segs.Temp_C.visible = true;
      return true;
    }
    return false;
  }

  /* Asleep, the pack's sleep show plays, drifting into its dream now and then. */
  function sleepMode(t, asleep) {
    var shows = pack.weather || {};
    if (!asleep) { asleepSince = null; return ''; }
    if (asleepSince === null) asleepSince = t;
    var slept = t - asleepSince;
    var dreaming = shows.dream && slept >= DREAM_AFTER && (slept - DREAM_AFTER) % DREAM_EVERY < DREAM_SECONDS;
    return dreaming ? 'dream' : shows.sleep ? 'sleep' : '';
  }

  function resize() {
    var w = Math.max(1, innerWidth), h = Math.max(1, innerHeight);
    renderer.setSize(w, h, false);
    if (composer) composer.setSize(w, h);
    camera.aspect = w / h;
    // keep all of Kit in view in a narrow window
    baseZ = w < h ? 6.4 * (h / w) * 0.85 : 6.4;
    camera.updateProjectionMatrix();
  }

  function draw() { if (composer) composer.render(); else renderer.render(scene, camera); }

  function tick() {
    requestAnimationFrame(tick);
    var dt = Math.min(clock.getDelta(), 0.1), t = clock.elapsedTime;
    if (show && t > show.until) endShow(false);
    // pull back while weather props are out so the cloud or sun stays in view
    var away = (show && show.kind) || mode ? 1 : 0;
    camera.position.z += (baseZ * (1 + 0.45 * away) - camera.position.z) * Math.min(1, dt * 4);
    camera.position.y += (0.25 + 0.3 * away - camera.position.y) * Math.min(1, dt * 4);
    camera.lookAt(0, 0.05 + 0.3 * away, 0);
    var st = want.state;
    var asleep = st === 'sleeping';
    var newMode = show ? '' : sleepMode(t, asleep);
    if (newMode !== mode) {
      var mw = (pack.weather || {})[newMode];
      if (mw) playClip(mw.move, !!mw.loop_move);
      else if (mode) playClip('idle');
      mode = newMode;
    }
    var modeShow = mode ? pack.weather[mode] : null;
    var moodName = state.showMood || (modeShow && modeShow.mood) || (st === 'offline' ? 'tired' : st === 'thinking' && state.mood === 'neutral' ? 'thinking' : state.mood);
    var m = mood(moodName);
    var k = 1 - Math.exp(-dt / Math.max(tuning.mood_blend_seconds || 0.35, 0.01) * 3);

    // face: mood, then state, gesture pulse and show, then blink, gaze and talk
    var keys = m.shape_keys || {}, name;
    for (name in cur) target[name] = keys[name] || 0;
    if (show && show.face) for (name in show.face) target[name] = Math.max(target[name] || 0, show.face[name]);
    if (modeShow) for (name in modeShow.shape_keys || {}) target[name] = Math.max(target[name] || 0, modeShow.shape_keys[name]);
    if (pulse) {
      var p = (t - pulse.start) / pulse.seconds;
      if (p >= 1) pulse = null;
      else {
        var amt = Math.sin(Math.PI * Math.min(1, p * 1.4));
        for (name in pulse.face) if (name in cur) target[name] = Math.max(target[name], pulse.face[name] * amt);
      }
    }
    if ('blush' in cur) target.blush = Math.max(0, Math.min(1, (target.blush || 0) + 0.15 * dials.valence));
    if (st === 'listening') { target.size_up = Math.min(1, (target.size_up || 0) + 0.2); target.brow_up = Math.min(1, (target.brow_up || 0) + 0.2); }
    if (asleep && !modeShow) { target.close_L = 0.92; target.close_R = 0.92; target.mouth_flat = 0.6; }
    nextBlink -= dt;
    if (!asleep && st !== 'offline' && nextBlink <= 0) {
      blinkT = 0.16; nextBlink = (tuning.blink_every_seconds || 4) * (1 + (0.5 - dials.arousal) * 0.6) * (0.6 + Math.random() * 0.8);
    }
    if (blinkT > 0) {
      blinkT -= dt;
      var b = Math.sin(Math.max(0, blinkT) / 0.16 * Math.PI);
      target.close_L = Math.max(target.close_L || 0, b); target.close_R = Math.max(target.close_R || 0, b);
    }
    var gx = 0, gy = 0;
    if (st === 'working') { gx = -0.6 + 1.2 * ((t / 1.6) % 1); gy = -0.3; }
    else if (want.look && t < want.look.until && st !== 'thinking' && !asleep) { gx = want.look.x; gy = -want.look.y; }
    gaze.x += (gx - gaze.x) * Math.min(1, dt * 8); gaze.y += (gy - gaze.y) * Math.min(1, dt * 8);
    target.look_right = Math.min(1, (target.look_right || 0) + Math.max(0, gaze.x) * 0.9);
    target.look_left = Math.min(1, (target.look_left || 0) + Math.max(0, -gaze.x) * 0.9);
    target.look_up = Math.min(1, (target.look_up || 0) + Math.max(0, gaze.y) * 0.7);
    target.look_down = Math.min(1, (target.look_down || 0) + Math.max(0, -gaze.y) * 0.7);
    if (st === 'speaking') target.mouth_open = Math.max(target.mouth_open || 0, 0.25 + 0.6 * Math.abs(Math.sin(t * 9) * Math.sin(t * 3.7 + 1)));
    for (name in cur) {
      cur[name] += ((target[name] || 0) - cur[name]) * (name.indexOf('close') === 0 && blinkT > 0 ? 1 : k);
      for (var i = 0; i < faceMeshes.length; i++) {
        var mesh = faceMeshes[i], idx = mesh.morphTargetDictionary[name];
        if (idx !== undefined) mesh.morphTargetInfluences[idx] = cur[name];
      }
    }
    var digits = show && t >= show.digitsAt && show.what.text;
    var segments = digits ? showSegments(show.what, t) : (hideSegments(), false);
    for (var j = 0; j < faceMeshes.length; j++) faceMeshes[j].visible = !digits;
    if (digitPlane) {
      digitPlane.visible = !!digits && !segments;
      if (digits && !segments) drawDigits(String(show.what.text), show.what.small || '');
    }

    // glow: the mood's colour, grey when offline, dim asleep
    var colour = st === 'offline' ? OFFLINE_COLOUR
      : tuning.glow_follows_mood === false ? mood('neutral').glow_colour : m.glow_colour;
    tmpC.set(colour || '#4dffc0').convertSRGBToLinear();
    curColour.lerp(tmpC, k);
    var glowTarget = asleep ? 0.35 : st === 'offline' ? 0.5 : 1;
    glowScale += (glowTarget - glowScale) * Math.min(1, dt * 2.5);
    var glow = (tuning.glow || 1.6) * glowScale;
    if (glowMat) { glowMat.color.setRGB(0, 0, 0); glowMat.emissive.copy(curColour); glowMat.emissiveIntensity = glow * 0.55; }
    if (digitPlane) digitPlane.material.color.copy(curColour).multiplyScalar(glow * 0.55);
    if (bloom) bloom.strength = 0.2 + glow * 0.2;

    // body: the baked move plus live idle motion scaled by energy and mood
    mixer.timeScale = (tuning.move_speed || 1) * (0.85 + 0.3 * dials.arousal); mixer.update(dt); propMixer.update(dt);
    // props pop in for the show playing (or the sleep and dream shows) and out after
    var out = (show && showProps[show.kind]) || (mode && showProps[mode]) || [];
    Object.keys(props).forEach(function (name) {
      var grp = props[name], pop = out.indexOf(name) >= 0 ? 1 : 0;
      if (pop && !grp.node.visible) { grp.shown = 0; grp.node.visible = true; grp.clips.forEach(function (a) { a.reset().play(); }); }
      grp.shown += (pop - grp.shown) * Math.min(1, dt * (pop ? 5 : 8));
      var x = grp.shown, s = pop ? x + Math.sin(x * Math.PI) * 0.18 : x;
      grp.node.scale.copy(grp.base).multiplyScalar(Math.max(0.001, s));
      if (!pop && x < 0.02 && grp.node.visible) { grp.node.visible = false; grp.clips.forEach(function (a) { a.stop(); }); }
    });
    var bolt = scene.getObjectByName('Lightning');
    var storm = props[(showProps.storm || [])[0]];
    if (bolt && storm && storm.node.visible && bolt.scale.x > 0.5) flash = 1;
    flash = Math.max(0, flash - dt * 5);
    hemi.intensity = 0.2 + flash * 1.6;
    var energyTarget = (tuning.energy || 1) * (asleep ? 0.05 : st === 'offline' ? 0.08 : (m.energy || 0.45));
    curEnergy += (energyTarget - curEnergy) * k;
    var E = curEnergy;
    curTilt += ((m.lean_degrees || 0) - curTilt) * k;
    pivot.position.y = -0.84 + 0.045 * E * (0.5 + 0.5 * Math.sin(t * (1.4 + 2.6 * E)));
    pivot.rotation.z = THREE.MathUtils.degToRad(curTilt) + 0.06 * E * Math.sin(t * (0.8 + 1.4 * E));
    pivot.rotation.y = 0.14 * E * Math.sin(t * 0.45) + gaze.x * 0.18;
    pivot.rotation.x = -gaze.y * 0.08;
    pivot.scale.set(1, 1 + (asleep ? 0.02 : 0.012) * Math.sin(t * (asleep ? 0.9 : 1.3)), 1);

    if (headBone) {
      headBone.getWorldPosition(tmpV);
      var lift = Math.max(0, tmpV.y + 0.84);
      shadow.scale.setScalar(Math.max(0.4, 1 - lift * 0.6));
      shadow.material.opacity = Math.max(0.15, 1 - lift * 0.9);
      shadow.position.x = tmpV.x;
    }
    draw();
  }

  // ---- reload when the brain has something new ----
  /* Reload when the brain has something new: the same new version on two checks in
     a row, so a pack Blender is still writing, or one odd answer, doesn't reload him. */
  function watch() {
    var seen = null;
    setInterval(function () {
      fetch('api/version?' + query(), { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (v) {
          if (!v || !info || v.version === info.version) { seen = null; return; }
          if (seen === v.version) { remember(); location.reload(); }
          seen = v.version;
        })
        .catch(function () {});
    }, POLL_MS);
  }

  // Ask the brain what to draw; if it can't be reached, keep asking (without
  // reloading the page, which would blank it each time).
  function start() {
    fetch('api/info?' + query(), { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        info = kit.info = data;
        watch();
        if (data.style !== 'model') { say('Kit is using a 2D look here.'); return; }
        pack = data.pack || {};
        moods = pack.moods || {};
        tuning = pack.tuning || {};
        gestures = data.look.gestures || {};
        try { init(); } catch (e) { say("This screen couldn't start 3D: " + e.message); }
      })
      .catch(function (e) { say("Can't reach Kit: " + e.message); setTimeout(start, POLL_MS); });
  }
  start();
})();
