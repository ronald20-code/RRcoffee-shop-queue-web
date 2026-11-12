/*
 * QueueFree RR Cafe – procedural 3D drinks (Three.js r128, global THREE).
 *
 * Every drink is built from the product's colours, so adding a drink in the
 * Django admin automatically gives it a 3D model.
 *
 *   QF3D.renderThumb(product, size)  -> PNG data URL (one shared WebGL context)
 *   new QF3D.Viewer(canvas)          -> live, drag-to-rotate viewer
 *       .show(product)
 */
(function (global) {
  "use strict";

  var C = function (hex) { return new THREE.Color(hex); };
  var lum = function (hex) { var c = C(hex); return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b; };

  function mat(color, o) {
    return new THREE.MeshStandardMaterial(Object.assign({ color: C(color), roughness: 0.6, metalness: 0 }, o || {}));
  }

  // deterministic pseudo-random so a drink always looks the same
  function rng(seed) {
    var s = (seed * 9301 + 49297) % 233280;
    return function () { s = (s * 9301 + 49297) % 233280; return s / 233280; };
  }

  function shadowDisc(r) {
    var cv = document.createElement("canvas");
    cv.width = cv.height = 128;
    var g = cv.getContext("2d");
    var gr = g.createRadialGradient(64, 64, 6, 64, 64, 64);
    gr.addColorStop(0, "rgba(43,24,16,0.42)");
    gr.addColorStop(1, "rgba(43,24,16,0)");
    g.fillStyle = gr;
    g.fillRect(0, 0, 128, 128);
    var m = new THREE.Mesh(
      new THREE.PlaneGeometry(r * 2, r * 2),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(cv), transparent: true, depthWrite: false })
    );
    m.rotation.x = -Math.PI / 2;
    m.position.y = 0.004;
    return m;
  }

  /* ---------- liquid surface (hot drinks): milk foam, latte art, toppings ---------- */
  function surface(p, g, y, r) {
    var liquid = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.05, 56), mat(p.liquid, { roughness: 0.3 }));
    liquid.position.y = y;
    g.add(liquid);
    var topY = y + 0.025;

    if (p.layer) {
      var foam = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.97, r * 0.97, 0.07, 56), mat(p.layer, { roughness: 0.92 }));
      foam.position.y = y + 0.045;
      g.add(foam);
      topY = y + 0.08;
      // simple latte-art: concentric rings pulled by a centre line
      for (var i = 1; i <= 3; i++) {
        var ring = new THREE.Mesh(new THREE.TorusGeometry(r * (0.18 + 0.2 * i), 0.016, 6, 48), mat(p.liquid, { roughness: 0.8 }));
        ring.rotation.x = Math.PI / 2;
        ring.position.set(0, topY, 0);
        g.add(ring);
      }
      var pull = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.012, r * 1.5), mat(p.liquid, { roughness: 0.8 }));
      pull.position.set(0, topY, 0);
      g.add(pull);
    }

    if (p.topping) {
      if (lum(p.topping) > 0.72) {
        // whipped cream swirl
        var radii = [0.46, 0.34, 0.22, 0.1], k;
        for (k = 0; k < radii.length; k++) {
          var s = new THREE.Mesh(new THREE.SphereGeometry(radii[k] * r / 0.85, 24, 16), mat(p.topping, { roughness: 0.95 }));
          s.scale.y = 0.62;
          s.position.set(0, topY + 0.08 + k * 0.17, 0);
          g.add(s);
        }
      } else {
        // caramel / sauce crosshatch drizzle
        for (var d = -2; d <= 2; d++) {
          [Math.PI / 4, -Math.PI / 4].forEach(function (ang) {
            var line = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.014, r * 1.4), mat(p.topping, { roughness: 0.25 }));
            line.rotation.y = ang;
            line.position.set(Math.cos(ang) * 0.0 + d * 0.16 * Math.cos(ang + Math.PI / 2), topY + 0.01, d * 0.16 * Math.sin(ang + Math.PI / 2) * -1);
            g.add(line);
          });
        }
      }
    }
  }

  function steam(g, y) {
    var puffs = [];
    var m = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.25, depthWrite: false });
    for (var i = 0; i < 6; i++) {
      var s = new THREE.Mesh(new THREE.SphereGeometry(0.16, 12, 10), m.clone());
      s.userData = { phase: i / 6, ox: (i % 3 - 1) * 0.22, oz: ((i + 1) % 3 - 1) * 0.2 };
      g.add(s);
      puffs.push(s);
    }
    return function (t) {
      puffs.forEach(function (s) {
        var ph = (t * 0.00028 + s.userData.phase) % 1;
        s.position.set(s.userData.ox + Math.sin(ph * 6) * 0.1, y + ph * 1.5, s.userData.oz);
        s.scale.setScalar(0.6 + ph * 1.3);
        s.material.opacity = 0.26 * (1 - ph) * Math.min(1, ph * 6);
      });
    };
  }

  /* ---------- cup builders ---------- */
  function buildPaperCup(p, g) {
    var H = 2.1, rT = 0.95, rB = 0.68;
    var rAt = function (y) { return rB + (rT - rB) * (y / H); };
    var wall = new THREE.Mesh(
      new THREE.LatheGeometry([new THREE.Vector2(0.001, 0), new THREE.Vector2(rB, 0), new THREE.Vector2(rT, H)], 56),
      mat("#fbf8f3", { side: THREE.DoubleSide, roughness: 0.8 })
    );
    g.add(wall);
    var rim = new THREE.Mesh(new THREE.TorusGeometry(rT, 0.045, 10, 56), mat("#fbf8f3", { roughness: 0.7 }));
    rim.rotation.x = Math.PI / 2;
    rim.position.y = H;
    g.add(rim);
    var y0 = 0.55, y1 = 1.45;
    g.add(new THREE.Mesh(
      new THREE.LatheGeometry([new THREE.Vector2(rAt(y0) + 0.02, y0), new THREE.Vector2(rAt(y1) + 0.02, y1)], 56),
      mat("#8a5a3a", { side: THREE.DoubleSide, roughness: 0.9 })
    ));
    var level = H * 0.86;
    surface(p, g, level, rAt(level) - 0.035);
    return steam(g, H + 0.1);
  }

  function buildMug(p, g) {
    var small = /espresso/i.test(p.name) && !/americano/i.test(p.name);
    var H = small ? 1.15 : 1.55, R = small ? 0.72 : 0.88;
    g.add(new THREE.Mesh(
      new THREE.LatheGeometry([new THREE.Vector2(0.001, 0), new THREE.Vector2(R, 0), new THREE.Vector2(R, H)], 56),
      mat("#faf6ef", { side: THREE.DoubleSide, roughness: 0.25 })
    ));
    var rim = new THREE.Mesh(new THREE.TorusGeometry(R, 0.05, 10, 56), mat("#faf6ef", { roughness: 0.25 }));
    rim.rotation.x = Math.PI / 2;
    rim.position.y = H;
    g.add(rim);
    var handle = new THREE.Mesh(new THREE.TorusGeometry(H * 0.28, 0.085, 12, 28, Math.PI), mat("#faf6ef", { roughness: 0.25 }));
    handle.rotation.z = -Math.PI / 2;
    handle.position.set(R + 0.01, H * 0.52, 0);
    g.add(handle);
    // saucer
    var saucer = new THREE.Mesh(
      new THREE.LatheGeometry([new THREE.Vector2(0.001, 0), new THREE.Vector2(R + 0.5, 0), new THREE.Vector2(R + 0.62, 0.12)], 56),
      mat("#f2ebe0", { side: THREE.DoubleSide, roughness: 0.3 })
    );
    g.add(saucer);
    var level = H * 0.88;
    surface(p, g, level, R - 0.05);
    return steam(g, H + 0.1);
  }

  function buildGlass(p, g) {
    var H = 2.35, rB = 0.72, rT = 0.93;
    var rAt = function (y) { return rB + (rT - rB) * (y / H); };

    var wall = new THREE.Mesh(
      new THREE.CylinderGeometry(rT, rB, H, 56, 1, true),
      new THREE.MeshStandardMaterial({ color: 0xd6ecf7, transparent: true, opacity: 0.2, roughness: 0.05, side: THREE.DoubleSide, depthWrite: false })
    );
    wall.position.y = H / 2;
    wall.renderOrder = 3;
    var base = new THREE.Mesh(
      new THREE.CylinderGeometry(rB, rB, 0.14, 56),
      new THREE.MeshStandardMaterial({ color: 0xd6ecf7, transparent: true, opacity: 0.4, roughness: 0.05 })
    );
    base.position.y = 0.07;
    var rim = new THREE.Mesh(new THREE.TorusGeometry(rT, 0.025, 8, 56), new THREE.MeshStandardMaterial({ color: 0xeaf6fc, transparent: true, opacity: 0.5, roughness: 0.1 }));
    rim.rotation.x = Math.PI / 2;
    rim.position.y = H;
    g.add(base, wall, rim);

    function seg(y0, y1, color, opacity) {
      var m = new THREE.Mesh(
        new THREE.CylinderGeometry(rAt(y1) - 0.035, rAt(y0) - 0.035, y1 - y0, 56),
        mat(color, { roughness: 0.2, transparent: true, opacity: opacity })
      );
      m.position.y = (y0 + y1) / 2;
      g.add(m);
    }
    var top = H * 0.84;
    if (p.layer) {
      seg(0.14, H * 0.46, p.layer, 0.96);
      seg(H * 0.46, top, p.liquid, 0.94);
    } else {
      seg(0.14, top, p.liquid, 0.92);
    }

    var tickers = [];
    if (p.ice) {
      var rand = rng(p.id || 7);
      var iceMat = new THREE.MeshStandardMaterial({ color: 0xeaf6ff, transparent: true, opacity: 0.6, roughness: 0.08 });
      for (var i = 0; i < 6; i++) {
        var cube = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 0.4), iceMat);
        var ang = rand() * Math.PI * 2, rad = rand() * 0.42;
        cube.position.set(Math.cos(ang) * rad, top - 0.28 - rand() * 0.5, Math.sin(ang) * rad);
        cube.rotation.set(rand() * 3, rand() * 3, rand() * 3);
        cube.userData = { y: cube.position.y, ph: rand() * 6 };
        g.add(cube);
        tickers.push(cube);
      }
    }
    if (p.straw) {
      var straw = new THREE.Group();
      for (var s = 0; s < 14; s++) {
        var piece = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.26, 12), mat(s % 2 ? "#f7f2e8" : "#e8564a", { roughness: 0.5 }));
        piece.position.y = s * 0.26;
        straw.add(piece);
      }
      straw.position.set(0.28, 0.35, 0.05);
      straw.rotation.z = -0.16;
      g.add(straw);
    }
    return function (t) {
      tickers.forEach(function (c) { c.position.y = c.userData.y + Math.sin(t * 0.0016 + c.userData.ph) * 0.035; });
    };
  }

  function buildDrink(p) {
    var g = new THREE.Group();
    var tick;
    if (p.cup === "glass") tick = buildGlass(p, g);
    else if (p.cup === "mug") tick = buildMug(p, g);
    else tick = buildPaperCup(p, g);
    g.add(shadowDisc(1.9));
    g.userData.tick = tick;
    return g;
  }

  function lights(scene) {
    scene.add(new THREE.HemisphereLight(0xfff4e6, 0x8a6a4e, 0.85));
    var key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(3, 6, 4);
    scene.add(key);
    var rimL = new THREE.DirectionalLight(0xffd9b0, 0.5);
    rimL.position.set(-4, 3, -3);
    scene.add(rimL);
  }

  function dispose(obj) {
    obj.traverse(function (o) {
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        (Array.isArray(o.material) ? o.material : [o.material]).forEach(function (m) {
          if (m.map) m.map.dispose();
          m.dispose();
        });
      }
    });
  }

  function fitCamera(cam, p) {
    var tall = p.cup === "glass" ? 1.3 : 1.05;
    cam.position.set(0, 3.1 + (tall - 1) * 1.5, 6.6);
    cam.lookAt(0, tall, 0);
  }

  /* ---------- thumbnails: one shared offscreen renderer ---------- */
  var thumbRenderer = null;
  function renderThumb(p, size) {
    size = size || 360;
    if (!thumbRenderer) {
      thumbRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      thumbRenderer.setPixelRatio(1);
    }
    thumbRenderer.setSize(size, size, false);
    var scene = new THREE.Scene();
    lights(scene);
    var cam = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
    fitCamera(cam, p);
    var drink = buildDrink(p);
    drink.rotation.y = 0.7;
    if (drink.userData.tick) drink.userData.tick(2200);
    scene.add(drink);
    thumbRenderer.render(scene, cam);
    var url = thumbRenderer.domElement.toDataURL("image/png");
    dispose(scene);
    return url;
  }

  /* ---------- live viewer ---------- */
  function Viewer(canvas) {
    var self = this;
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(global.devicePixelRatio || 1, 2));
    this.scene = new THREE.Scene();
    lights(this.scene);
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
    this.holder = new THREE.Group();
    this.scene.add(this.holder);
    this.rotY = 0.6;
    this.spin = 0.006;
    this.dragging = false;
    this.product = null;
    this.running = true;

    canvas.style.touchAction = "none";
    canvas.addEventListener("pointerdown", function (e) {
      self.dragging = true; self.lastX = e.clientX; canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", function (e) {
      if (!self.dragging) return;
      self.rotY += (e.clientX - self.lastX) * 0.012;
      self.lastX = e.clientX;
    });
    var end = function () { self.dragging = false; };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);

    this._onResize = function () { self.resize(); };
    global.addEventListener("resize", this._onResize);
    this.resize();
    requestAnimationFrame(function loop(t) {
      if (!self.running) return;
      if (!self.dragging) self.rotY += self.spin;
      self.holder.rotation.y = self.rotY;
      var d = self.holder.children[0];
      if (d && d.userData.tick) d.userData.tick(t);
      self.renderer.render(self.scene, self.camera);
      requestAnimationFrame(loop);
    });
  }
  Viewer.prototype.resize = function () {
    var w = this.canvas.clientWidth || 400, h = this.canvas.clientHeight || 400;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  };
  Viewer.prototype.show = function (p) {
    while (this.holder.children.length) {
      var old = this.holder.children[0];
      this.holder.remove(old);
      dispose(old);
    }
    this.product = p;
    this.holder.add(buildDrink(p));
    fitCamera(this.camera, p);
    this.resize();
  };
  Viewer.prototype.destroy = function () {
    this.running = false;
    global.removeEventListener("resize", this._onResize);
    dispose(this.scene);
    this.renderer.dispose();
  };

  global.QF3D = { renderThumb: renderThumb, Viewer: Viewer };
})(window);
