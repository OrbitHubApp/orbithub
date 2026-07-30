(() => {
window.OrbitFavorites = {
    refreshPanel: function () {
      var body = document.getElementById("favorites-panel-body");
      if (!body) return Promise.resolve();
      return fetch("/api/favorites/panel-html")
        .then(function (r) { return r.text(); })
        .then(function (html) {
          body.innerHTML = html;
          window.OrbitFavorites.wirePanel();
        });
    },
    add: function (noradId) {
      return fetch("/api/favorites/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ norad_id: noradId }),
      }).then(function () {
        return window.OrbitFavorites.refreshPanel();
      });
    },
    remove: function (noradId) {
      return fetch("/api/favorites/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ norad_id: noradId }),
      }).then(function () {
        return window.OrbitFavorites.refreshPanel();
      });
    },
    wirePanel: function () {
      var body = document.getElementById("favorites-panel-body");
      if (!body) return;
      body.querySelectorAll(".visibility-bright-card[data-href]").forEach(function (card) {
        card.addEventListener("click", function (event) {
          if (event.target.closest(".favorite-remove-button")) return;
          window.location.href = card.getAttribute("data-href");
        });
        card.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            window.location.href = card.getAttribute("data-href");
          }
        });
      });
      body.querySelectorAll(".favorite-remove-button").forEach(function (button) {
        button.addEventListener("click", function (event) {
          event.stopPropagation();
          window.OrbitFavorites.remove(button.getAttribute("data-norad-id"));
        });
      });
    },
  };

  document.addEventListener("DOMContentLoaded", function () {
    window.OrbitFavorites.wirePanel();
  });
})();

(() => {
  const refreshSeconds = Number(
    document.body.dataset.refreshSeconds || 60
  );

  const clock = document.getElementById("local-clock");
  const clockUseUtc = document.body.dataset.timeDisplay === "utc";
  const countdown = document.getElementById(
    "refresh-countdown"
  );

  let remaining = refreshSeconds;

  function updateClock() {
    if (!clock) {
      return;
    }

    clock.textContent = new Intl.DateTimeFormat(
      "de-DE",
      {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        timeZone: clockUseUtc ? "UTC" : undefined,
      }
    ).format(new Date());
  }

  function updateCountdown() {
    const refreshPauseElement =
      document.querySelector(
        "[data-pause-auto-refresh]:not([hidden])"
      );

    if (refreshPauseElement) {
      remaining = refreshSeconds;

      if (countdown) {
        countdown.textContent = String(
          refreshSeconds
        );
      }

      return;
    }

    remaining -= 1;

    if (countdown) {
      countdown.textContent = String(
        Math.max(remaining, 0)
      );
    }

    if (remaining <= 0) {
      window.location.reload();
    }
  }

  updateClock();

  window.setInterval(updateClock, 1000);
  window.setInterval(updateCountdown, 1000);
})();

(() => {
  const menuButton = document.getElementById(
    "mobile-menu-button"
  );

  const overlay = document.getElementById(
    "sidebar-overlay"
  );

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");

    if (menuButton) {
      menuButton.setAttribute(
        "aria-expanded",
        "false"
      );
    }
  }

  function toggleSidebar() {
    const isOpen = document.body.classList.toggle(
      "sidebar-open"
    );

    if (menuButton) {
      menuButton.setAttribute(
        "aria-expanded",
        String(isOpen)
      );
    }
  }

  if (menuButton) {
    menuButton.addEventListener(
      "click",
      toggleSidebar
    );
  }

  if (overlay) {
    overlay.addEventListener(
      "click",
      closeSidebar
    );
  }

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSidebar();
    }
  });
})();

(() => {
  const elements = {
    cpu: document.getElementById("system-cpu"),
    memory: document.getElementById("system-memory"),
    temperature: document.getElementById(
      "system-temperature"
    ),
    disk: document.getElementById("system-disk"),
  };

  function formatPercent(value) {
    return Number.isFinite(value)
      ? `${value.toFixed(1)} %`
      : "-";
  }

  function formatTemperature(value) {
    return Number.isFinite(value)
      ? `${value.toFixed(1)} °C`
      : "-";
  }

  async function updateSystemMetrics() {
    try {
      const response = await fetch(
        "/api/system",
        {
          headers: {
            Accept: "application/json",
          },
          cache: "no-store",
        }
      );

      if (!response.ok) {
        throw new Error(
          `System API returned ${response.status}`
        );
      }

      const data = await response.json();

      if (elements.cpu) {
        elements.cpu.textContent = formatPercent(
          data.cpu_percent
        );
      }

      if (elements.memory) {
        elements.memory.textContent = formatPercent(
          data.memory_percent
        );
      }

      if (elements.temperature) {
        elements.temperature.textContent =
          formatTemperature(
            data.temperature_celsius
          );

        const card =
          elements.temperature.closest(
            ".temperature-card"
          );

        if (card) {
          card.classList.toggle(
            "temperature-warning",
            Number.isFinite(
              data.temperature_celsius
            ) &&
              data.temperature_celsius >= 70
          );
        }
      }

      if (elements.disk) {
        elements.disk.textContent = formatPercent(
          data.disk_percent
        );
      }


    } catch (error) {
      console.error(
        "OrbitHub system metrics update failed:",
        error
      );
    }
  }

  updateSystemMetrics();

  window.setInterval(
    updateSystemMetrics,
    10000
  );
})();

(() => {
  const updateButton = document.getElementById(
    "update-dataset-button"
  );

  const updateStatus = document.getElementById(
    "dataset-update-status"
  );

  if (!updateButton) {
    return;
  }

  const label = updateButton.querySelector(
    ".update-button-label"
  );

  const icon = updateButton.querySelector(
    ".update-button-icon"
  );

  function setStatus(message, state = "") {
    if (!updateStatus) {
      return;
    }

    updateStatus.textContent = message;
    updateStatus.className =
      `dataset-update-status ${state}`.trim();
  }

  updateButton.addEventListener(
    "click",
    async () => {
      updateButton.disabled = true;
      updateButton.classList.add("is-updating");

      if (label) {
        label.textContent =
          "Datensätze werden geladen …";
      }

      if (icon) {
        icon.setAttribute("aria-hidden", "true");
      }

      setStatus(
        "OrbitHub lädt aktuelle TLE-Daten von der Quelle. " +
        "Dies kann etwa ein bis zwei Minuten dauern.",
        "is-running"
      );

      try {
        const response = await fetch(
          "/update",
          {
            method: "POST",
            headers: {
              Accept: "application/json",
            },
            cache: "no-store",
          }
        );

        let result = null;

        try {
          result = await response.json();
        } catch {
          result = null;
        }

        if (!response.ok) {
          const detail =
            result?.detail ||
            `HTTP-Fehler ${response.status}`;

          throw new Error(detail);
        }

        setStatus(
          "Aktualisierung erfolgreich abgeschlossen. " +
          "Das Dashboard wird neu geladen.",
          "is-success"
        );

        if (label) {
          label.textContent =
            "Aktualisierung abgeschlossen";
        }

        window.setTimeout(() => {
          window.location.reload();
        }, 1500);
      } catch (error) {
        console.error(
          "OrbitHub dataset update failed:",
          error
        );

        setStatus(
          `Aktualisierung fehlgeschlagen: ${
            error.message
          }`,
          "is-error"
        );

        if (label) {
          label.textContent =
            "Erneut aktualisieren";
        }

        updateButton.disabled = false;
        updateButton.classList.remove(
          "is-updating"
        );
      }
    }
  );
})();

(() => {
  const timezoneElement = document.getElementById(
    "local-time-zone"
  );

  function updateLocalTimezoneLabel() {
    if (!timezoneElement) {
      return;
    }

    if (document.body.dataset.timeDisplay === "utc") {
      timezoneElement.textContent = "GMT";
      return;
    }

    try {
      const parts = new Intl.DateTimeFormat(
        "de-DE",
        {
          timeZone: "Europe/Berlin",
          timeZoneName: "short",
        }
      ).formatToParts(new Date());

      const zone = parts.find(
        (part) => part.type === "timeZoneName"
      )?.value;

      timezoneElement.textContent = zone
        ? `Ortszeit (${zone})`
        : "Ortszeit";
    } catch {
      timezoneElement.textContent = "Ortszeit";
    }
  }

  updateLocalTimezoneLabel();
})();

(() => {
  const updateCard = document.getElementById(
    "last-update-card"
  );

  const relativeElement = document.getElementById(
    "last-update-relative"
  );

  if (!updateCard || !relativeElement) {
    return;
  }

  function parseGermanUtcTimestamp(value) {
    if (!value) {
      return null;
    }

    const match = value.match(
      /(\d{2})\.(\d{2})\.(\d{4})\D+(\d{2}):(\d{2}):(\d{2})/
    );

    if (!match) {
      return null;
    }

    const [
      ,
      day,
      month,
      year,
      hour,
      minute,
      second,
    ] = match;

    return new Date(
      Date.UTC(
        Number(year),
        Number(month) - 1,
        Number(day),
        Number(hour),
        Number(minute),
        Number(second)
      )
    );
  }

  function formatRelativeTime(milliseconds) {
    const seconds = Math.max(
      0,
      Math.floor(milliseconds / 1000)
    );

    if (seconds < 60) {
      return "vor weniger als 1 Min.";
    }

    const minutes = Math.floor(seconds / 60);

    if (minutes < 60) {
      return minutes === 1
        ? "vor 1 Min."
        : `vor ${minutes} Min.`;
    }

    const hours = Math.floor(minutes / 60);

    if (hours < 24) {
      return hours === 1
        ? "vor 1 Std."
        : `vor ${hours} Std.`;
    }

    const days = Math.floor(hours / 24);

    return days === 1
      ? "vor 1 Tag"
      : `vor ${days} Tagen`;
  }

  function updateRelativeTime() {
    const timestamp = parseGermanUtcTimestamp(
      updateCard.dataset.updateUtc
    );

    if (!timestamp) {
      relativeElement.textContent =
        "Zeitabstand nicht verfügbar";
      return;
    }

    relativeElement.textContent =
      formatRelativeTime(
        Date.now() - timestamp.getTime()
      );
  }

  updateRelativeTime();

  window.setInterval(
    updateRelativeTime,
    30000
  );
})();

(() => {
  const panel = document.getElementById("pass-countdown");

  if (!panel) {
    return;
  }

  const labelEl = document.getElementById("pass-countdown-label");
  const valueEl = document.getElementById("pass-countdown-value");

  function pad(number) {
    return String(number).padStart(2, "0");
  }

  function formatDuration(milliseconds) {
    const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds);
  }

  let intervalId = null;

  function updateCountdown() {
    const riseTime = new Date(panel.dataset.riseUtc);
    const setTime = new Date(panel.dataset.setUtc);

    if (Number.isNaN(riseTime.getTime()) || Number.isNaN(setTime.getTime())) {
      labelEl.textContent = "Kein Überflug geplant";
      valueEl.textContent = "--:--:--";
      return;
    }

    const now = new Date();

    if (now < riseTime) {
      labelEl.textContent = "Nächster Überflug in";
      valueEl.textContent = formatDuration(riseTime - now);
      panel.classList.remove("is-active");
    } else if (now < setTime) {
      labelEl.textContent = "Überflug läuft · LOS in";
      valueEl.textContent = formatDuration(setTime - now);
      panel.classList.add("is-active");
    } else {
      labelEl.textContent = "Überflug beendet";
      valueEl.textContent = "00:00:00";
      panel.classList.remove("is-active");

      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }
    }
  }

  updateCountdown();
  intervalId = window.setInterval(updateCountdown, 1000);
})();

(() => {
  const dataEl = document.getElementById("passes-data");

  if (!dataEl) {
    return;
  }

  let passList;

  try {
    passList = JSON.parse(dataEl.textContent);
  } catch (error) {
    return;
  }

  const rows = document.querySelectorAll(".pass-row");
  const countdownPanel = document.getElementById("pass-countdown");

  const summaryRise = document.getElementById("summary-rise");
  const summaryMax = document.getElementById("summary-max");
  const summarySet = document.getElementById("summary-set");
  const summaryElevation = document.getElementById("summary-elevation");
  const summaryAzimuthRise = document.getElementById("summary-azimuth-rise");
  const summaryAzimuthSet = document.getElementById("summary-azimuth-set");
  const summaryDuration = document.getElementById("summary-duration");
  const nextPassSummary = document.getElementById("next-pass-summary");

  const track = document.getElementById("polarplot-track");
  const riseDot = document.getElementById("polarplot-rise");
  const setDot = document.getElementById("polarplot-set");
  const aosLabel = document.getElementById("polarplot-aos-label");
  const losLabel = document.getElementById("polarplot-los-label");

  const mapContainer = document.getElementById("ground-map");
  let groundMap = null;
  let obsLat = null;
  let obsLon = null;
  let trackLine = null;
  let footprintCircle = null;
  let riseMarker = null;
  let setMarker = null;
  let satMarker = null;

  if (mapContainer && window.L) {
    obsLat = Number(mapContainer.dataset.observerLat);
    obsLon = Number(mapContainer.dataset.observerLon);

    groundMap = L.map(mapContainer, { worldCopyJump: true }).setView(
      [obsLat, obsLon],
      3,
    );

    L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: "abcd",
        maxZoom: 19,
      },
    ).addTo(groundMap);

    L.circleMarker([obsLat, obsLon], {
      radius: 6,
      color: "#f2c14e",
      fillColor: "#f2c14e",
      fillOpacity: 0.9,
      weight: 2,
    })
      .addTo(groundMap)
      .bindTooltip(mapContainer.dataset.observerName || "Standort");
  }

  function footprintRadiusMeters(altitudeKm) {
    const earthRadiusKm = 6371;
    const ratio = earthRadiusKm / (earthRadiusKm + altitudeKm);
    const clamped = Math.min(1, Math.max(-1, ratio));
    const centralAngle = Math.acos(clamped);
    return earthRadiusKm * centralAngle * 1000;
  }

  function splitAntimeridian(latLngs) {
    const segments = [[]];
    latLngs.forEach((point, index) => {
      const previous = latLngs[index - 1];
      if (previous && Math.abs(point[1] - previous[1]) > 180) {
        segments.push([]);
      }
      segments[segments.length - 1].push(point);
    });
    return segments.length > 1 ? segments : latLngs;
  }

  function pad(number) {
    return String(number).padStart(2, "0");
  }

  function formatTime(date) {
    const useUtc = document.body.dataset.timeDisplay === "utc";
    const hours = useUtc ? date.getUTCHours() : date.getHours();
    const minutes = useUtc ? date.getUTCMinutes() : date.getMinutes();
    const seconds = useUtc ? date.getUTCSeconds() : date.getSeconds();
    return pad(hours) + ":" + pad(minutes) + ":" + pad(seconds);
  }

  function formatDateTime(date) {
    const useUtc = document.body.dataset.timeDisplay === "utc";
    const day = useUtc ? date.getUTCDate() : date.getDate();
    const month = useUtc ? date.getUTCMonth() : date.getMonth();
    const year = useUtc ? date.getUTCFullYear() : date.getFullYear();
    return (
      pad(day) +
      "." +
      pad(month + 1) +
      "." +
      year +
      " " +
      formatTime(date)
    );
  }

  function formatDuration(totalSeconds) {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return minutes + " Min. " + seconds + " Sek.";
  }

  function applyPass(index) {
    const passData = passList[index];

    if (!passData) {
      return;
    }

    const rise = new Date(passData.rise_iso);
    const culmination = new Date(passData.culmination_iso);
    const set = new Date(passData.set_iso);

    if (summaryRise) summaryRise.textContent = formatTime(rise);
    if (summaryMax) summaryMax.textContent = formatTime(culmination);
    if (summarySet) summarySet.textContent = formatTime(set);
    if (summaryElevation) summaryElevation.textContent = passData.max_elevation_deg.toFixed(1) + "°";
    if (summaryAzimuthRise) summaryAzimuthRise.textContent = passData.rise_azimuth_deg.toFixed(1) + "°";
    if (summaryAzimuthSet) summaryAzimuthSet.textContent = passData.set_azimuth_deg.toFixed(1) + "°";
    if (summaryDuration) summaryDuration.textContent = formatDuration(passData.duration_seconds);

    if (nextPassSummary) {
      nextPassSummary.textContent =
        formatDateTime(rise) + " bis " + formatTime(set) + " · Maximum " + passData.max_elevation_deg.toFixed(1) + "°";
    }

    if (track && passData.track_points.length > 0) {
      track.setAttribute(
        "points",
        passData.track_points.map((point) => point.x + "," + point.y).join(" ")
      );

      const firstPoint = passData.track_points[0];
      const lastPoint = passData.track_points[passData.track_points.length - 1];

      if (riseDot) {
        riseDot.setAttribute("cx", firstPoint.x);
        riseDot.setAttribute("cy", firstPoint.y);
      }

      if (setDot) {
        setDot.setAttribute("cx", lastPoint.x);
        setDot.setAttribute("cy", lastPoint.y);
      }

      if (aosLabel) {
        aosLabel.setAttribute("x", firstPoint.x);
        aosLabel.setAttribute("y", firstPoint.y - 7);
      }

      if (losLabel) {
        losLabel.setAttribute("x", lastPoint.x);
        losLabel.setAttribute("y", lastPoint.y - 7);
      }
    }

  if (groundMap && passData.track_points.length > 0) {
    const points = passData.track_points;
    const latLngs = splitAntimeridian(
      points.map((point) => [point.lat, point.lon]),
    );

    if (trackLine) groundMap.removeLayer(trackLine);
    trackLine = L.polyline(latLngs, {
      color: "#4ec9f0",
      weight: 3,
      opacity: 0.85,
    }).addTo(groundMap);

    const peak = points.reduce(
      (best, point) => (point.el > best.el ? point : best),
      points[0],
    );

    if (footprintCircle) groundMap.removeLayer(footprintCircle);
    footprintCircle = L.circle([peak.lat, peak.lon], {
      radius: footprintRadiusMeters(peak.alt_km),
      color: "#4ec9f0",
      weight: 1,
      fillColor: "#4ec9f0",
      fillOpacity: 0.08,
      dashArray: "4 6",
    }).addTo(groundMap);

    const first = points[0];
    const last = points[points.length - 1];

    if (riseMarker) groundMap.removeLayer(riseMarker);
    riseMarker = L.circleMarker([first.lat, first.lon], {
      radius: 5,
      color: "#5fd97a",
      fillColor: "#5fd97a",
      fillOpacity: 1,
    })
      .addTo(groundMap)
      .bindTooltip("AOS");

    if (setMarker) groundMap.removeLayer(setMarker);
    setMarker = L.circleMarker([last.lat, last.lon], {
      radius: 5,
      color: "#e0575b",
      fillColor: "#e0575b",
      fillOpacity: 1,
    })
      .addTo(groundMap)
      .bindTooltip("LOS");

    if (satMarker) groundMap.removeLayer(satMarker);
    satMarker = L.circleMarker([peak.lat, peak.lon], {
      radius: 4,
      color: "#ffffff",
      fillColor: "#0b1b2b",
      fillOpacity: 1,
      weight: 2,
    }).addTo(groundMap);

    const boundsSource = points.map((point) => [point.lat, point.lon]);
    const bounds = L.latLngBounds(boundsSource);
    if (obsLat !== null && obsLon !== null) {
      bounds.extend([obsLat, obsLon]);
    }
    groundMap.fitBounds(bounds, { padding: [24, 24], maxZoom: 6 });
  }

    if (countdownPanel) {
      countdownPanel.dataset.riseUtc = passData.rise_iso;
      countdownPanel.dataset.setUtc = passData.set_iso;
    }

    rows.forEach((row) => {
      row.classList.toggle("active", Number(row.dataset.passIndex) === index);
    });
  }

  rows.forEach((row) => {
    row.addEventListener("click", () => {
      applyPass(Number(row.dataset.passIndex));
    });
  });
})();

/* --- OrbitHub Merkliste (Watchlist) fuer die Ueberfluege-Seite --- */
(() => {
  const dataEl = document.getElementById("watchlist-passes-data");

  if (!dataEl) {
    return;
  }

  let passList;

  try {
    passList = JSON.parse(dataEl.textContent);
  } catch (error) {
    return;
  }

  const rows = document.querySelectorAll(".watchlist-pass-row");
  const track = document.getElementById("watchlist-polarplot-track");
  const riseDot = document.getElementById("watchlist-polarplot-rise");
  const setDot = document.getElementById("watchlist-polarplot-set");
  const aosLabel = document.getElementById("watchlist-polarplot-aos-label");
  const losLabel = document.getElementById("watchlist-polarplot-los-label");
  const satelliteNameEl = document.getElementById("watchlist-satellite-name");
  const satelliteNoradEl = document.getElementById(
    "watchlist-satellite-norad",
  );

  function applyWatchlistPass(index) {
    const passData = passList[index];

    if (!passData) {
      return;
    }

    if (satelliteNameEl) {
      satelliteNameEl.textContent = passData.satellite_name;
    }
    if (satelliteNoradEl) {
      satelliteNoradEl.textContent = passData.satellite_norad_id;
    }

    if (track && passData.track_points.length > 0) {
      track.setAttribute(
        "points",
        passData.track_points
          .map((point) => point.x + "," + point.y)
          .join(" "),
      );

      const firstPoint = passData.track_points[0];
      const lastPoint = passData.track_points[passData.track_points.length - 1];

      if (riseDot) {
        riseDot.setAttribute("cx", firstPoint.x);
        riseDot.setAttribute("cy", firstPoint.y);
      }
      if (setDot) {
        setDot.setAttribute("cx", lastPoint.x);
        setDot.setAttribute("cy", lastPoint.y);
      }
      if (aosLabel) {
        aosLabel.setAttribute("x", firstPoint.x);
        aosLabel.setAttribute("y", firstPoint.y - 7);
      }
      if (losLabel) {
        losLabel.setAttribute("x", lastPoint.x);
        losLabel.setAttribute("y", lastPoint.y - 7);
      }
    }

    rows.forEach((row) => {
      row.classList.toggle(
        "active",
        Number(row.dataset.watchlistPassIndex) === index,
      );
    });
  }

  rows.forEach((row) => {
    row.addEventListener("click", () => {
      applyWatchlistPass(Number(row.dataset.watchlistPassIndex));
    });
  });
})();

/* --- OrbitHub Merkliste: Satelliten hinzufuegen/entfernen --- */
(() => {
  const addForm = document.getElementById("watchlist-add-form");
  const addSelect = document.getElementById("watchlist-add-select");
  const chipsContainer = document.getElementById("watchlist-chips");

  async function postFavorite(url, noradId) {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ norad_id: noradId }),
      });

      if (response.ok) {
        window.location.reload();
      }
    } catch (error) {
      /* Netzwerkfehler ignorieren */
    }
  }

  if (addForm && addSelect) {
    addForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const noradId = addSelect.value;

      if (!noradId) {
        return;
      }

      postFavorite("/api/favorites/add", noradId);
    });
  }

  if (chipsContainer) {
    chipsContainer
      .querySelectorAll(".watchlist-chip-remove")
      .forEach((button) => {
        button.addEventListener("click", () => {
          const noradId = button.dataset.noradId;

          if (!noradId) {
            return;
          }

          postFavorite("/api/favorites/remove", noradId);
        });
      });
  }
})();

/* --- OrbitHub Ueberfluege: Satelliten-Kombifeld (durchsuchbar) ---
   Gleiches Muster wie auf der Sichtbarkeit-Seite (siehe visibility.html):
   Bei ca. 32000 Satelliten respektiert Chrome das hidden-Attribut auf
   <option> im aufgeklappten <select>-Popup nicht zuverlaessig. Daher bleibt
   das <select> unsichtbar (nur Formularwert) und ein Text-Eingabefeld mit
   eigener, immer sichtbarer Trefferliste (<ul>) uebernimmt die Auswahl. */
(() => {
  function initSatelliteCombo(config) {
    const select = document.getElementById(config.selectId);
    const input = document.getElementById(config.inputId);
    const list = document.getElementById(config.listId);
    const clearButton = config.clearId
      ? document.getElementById(config.clearId)
      : null;

    if (!select || !input || !list) {
      return;
    }

    const options = Array.prototype.map
      .call(select.options, (opt) => ({
        value: opt.value,
        label: opt.textContent.replace(/\s+/g, " ").trim(),
      }))
      .filter((opt) => opt.value !== "");

    function updateClearButtonVisibility() {
      if (!clearButton) {
        return;
      }
      clearButton.hidden = !select.value;
    }
    updateClearButtonVisibility();

    let currentMatches = [];
    let activeIndex = -1;

    function closeList() {
      list.hidden = true;
      list.innerHTML = "";
      currentMatches = [];
      activeIndex = -1;
    }

    function syncInputToSelection() {
      const current = select.options[select.selectedIndex];
      input.value = current
        ? current.textContent.replace(/\s+/g, " ").trim()
        : "";
      updateClearButtonVisibility();
    }

    function selectOption(opt) {
      select.value = opt.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      input.value = opt.label;
      closeList();
      updateClearButtonVisibility();
    }

    function updateActive(items) {
      items.forEach((li, idx) => {
        li.classList.toggle("is-active", idx === activeIndex);
      });
      if (items[activeIndex]) {
        items[activeIndex].scrollIntoView({ block: "nearest" });
      }
    }

    function renderList(matches) {
      currentMatches = matches;
      activeIndex = -1;
      list.innerHTML = "";
      if (!matches.length) {
        closeList();
        return;
      }
      matches.slice(0, 60).forEach((opt, idx) => {
        const li = document.createElement("li");
        li.textContent = opt.label;
        li.setAttribute("role", "option");
        li.dataset.index = String(idx);
        li.addEventListener("mousedown", (event) => {
          event.preventDefault();
          selectOption(opt);
        });
        list.appendChild(li);
      });
      list.hidden = false;
    }

    function filterAndRender(query) {
      const q = query.trim().toLowerCase();
      if (!q) {
        renderList(options.slice(0, 60));
        return;
      }
      const matches = options.filter(
        (opt) => opt.label.toLowerCase().indexOf(q) !== -1,
      );
      renderList(matches);
    }

    input.addEventListener("focus", () => {
      filterAndRender(input.value);
    });

    input.addEventListener("input", () => {
      filterAndRender(input.value);
    });

    input.addEventListener("keydown", (event) => {
      if (list.hidden) {
        if (event.key === "ArrowDown" || event.key === "Enter") {
          filterAndRender(input.value);
        }
        return;
      }
      const items = list.querySelectorAll("li");
      if (event.key === "ArrowDown") {
        event.preventDefault();
        activeIndex = Math.min(activeIndex + 1, items.length - 1);
        updateActive(items);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        updateActive(items);
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (activeIndex >= 0 && currentMatches[activeIndex]) {
          selectOption(currentMatches[activeIndex]);
        } else if (currentMatches.length === 1) {
          selectOption(currentMatches[0]);
        }
      } else if (event.key === "Escape") {
        closeList();
        syncInputToSelection();
      }
    });

    input.addEventListener("blur", () => {
      window.setTimeout(() => {
        closeList();
        syncInputToSelection();
      }, 120);
    });

    if (clearButton) {
      clearButton.addEventListener("click", (event) => {
        event.preventDefault();
        select.value = "";
        select.dispatchEvent(new Event("change", { bubbles: true }));
        input.value = "";
        updateClearButtonVisibility();
        input.focus();
        filterAndRender("");
      });
    }
  }

  document.addEventListener("click", (event) => {
    document.querySelectorAll(".satellite-combobox-wrap").forEach((wrap) => {
      if (!wrap.contains(event.target)) {
        const list = wrap.querySelector(".satellite-combo-list");
        if (list && !list.hidden) {
          list.hidden = true;
          list.innerHTML = "";
        }
      }
    });
  });

  initSatelliteCombo({
    selectId: "passes-satellite-select",
    inputId: "passes-satellite-combo-input",
    listId: "passes-satellite-combo-list",
    clearId: "passes-satellite-combo-clear",
  });

  initSatelliteCombo({
    selectId: "watchlist-add-select",
    inputId: "watchlist-add-combo-input",
    listId: "watchlist-add-combo-list",
    clearId: "watchlist-add-combo-clear",
  });
})();

/* --- OrbitHub: Update-Check gegen GitHub (Sidebar-Button) --- */
(function () {
  "use strict";

  var button = document.getElementById("update-check-button");
  var result = document.getElementById("update-check-result");

  if (!button || !result) {
    return;
  }

  function setResult(mainText, codeText, stateClass, linkHref, linkText) {
    result.textContent = "";
    result.className = "update-check-result";
    if (stateClass) {
      result.classList.add(stateClass);
    }
    result.hidden = false;

    var main = document.createElement("div");
    main.textContent = mainText;
    result.appendChild(main);

    if (codeText) {
      var code = document.createElement("code");
      code.textContent = codeText;
      result.appendChild(code);
    }

    if (linkHref) {
      var link = document.createElement("a");
      link.href = linkHref;
      link.className = "update-check-link";
      link.textContent = linkText || linkHref;
      result.appendChild(link);
    }
  }

  button.addEventListener("click", function () {
    if (button.classList.contains("is-loading")) {
      return;
    }
    button.classList.add("is-loading");
    result.hidden = true;

    fetch("/api/update/check")
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        if (!data || !data.ok) {
          setResult(
            (data && data.error) || "Pruefung nicht moeglich.",
            null,
            "is-error"
          );
          return;
        }

        if (data.update_available) {
          var label =
            "Update verfuegbar: v" +
            data.current_version +
            " → v" +
            data.latest_version +
            (data.latest_codename ? " (" + data.latest_codename + ")" : "");
          setResult(
            label,
            data.update_command,
            "is-available",
            "/update",
            "Anleitung ansehen â"
          );
        } else {
          setResult(
            "Du hast die aktuellste Version (v" +
              data.current_version +
              (data.current_codename ? " – " + data.current_codename : "") +
              ").",
            null,
            "is-uptodate"
          );
        }
      })
      .catch(function () {
        setResult(
          "Pruefung nicht moeglich - keine Verbindung zu GitHub.",
          null,
          "is-error"
        );
      })
      .finally(function () {
        button.classList.remove("is-loading");
      });
  });
})();

/* --- OrbitHub: Update-Seite - Statusanzeige beim Laden --- */
(function () {
  "use strict";

  var statusEl = document.getElementById("update-status-text");
  if (!statusEl) {
    return;
  }

  fetch("/api/update/check")
    .then(function (response) {
      return response.json();
    })
    .then(function (data) {
      statusEl.className = "";
      if (!data || !data.ok) {
        statusEl.textContent =
          (data && data.error) || "Pruefung nicht moeglich.";
        statusEl.classList.add("is-error");
        return;
      }

      if (data.update_available) {
        statusEl.textContent =
          "Neue Version verfuegbar: v" +
          data.current_version +
          " → v" +
          data.latest_version +
          (data.latest_codename ? " (" + data.latest_codename + ")" : "") +
          ". Folge den Schritten unten, um zu aktualisieren.";
        statusEl.classList.add("is-available");
      } else {
        statusEl.textContent =
          "Du hast bereits die aktuellste Version (v" +
          data.current_version +
          (data.current_codename ? " – " + data.current_codename : "") +
          ").";
        statusEl.classList.add("is-uptodate");
      }
    })
    .catch(function () {
      statusEl.textContent =
        "Pruefung nicht moeglich - keine Verbindung zu GitHub.";
      statusEl.classList.add("is-error");
    });

  
})();

