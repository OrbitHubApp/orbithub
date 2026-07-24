(() => {
  const refreshSeconds = Number(
    document.body.dataset.refreshSeconds || 60
  );

  const clock = document.getElementById("local-clock");
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
      : "–";
  }

  function formatTemperature(value) {
    return Number.isFinite(value)
      ? `${value.toFixed(1)} °C`
      : "–";
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

  function pad(number) {
    return String(number).padStart(2, "0");
  }

  function formatTime(date) {
    return pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds());
  }

  function formatDateTime(date) {
    return (
      pad(date.getDate()) +
      "." +
      pad(date.getMonth() + 1) +
      "." +
      date.getFullYear() +
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
