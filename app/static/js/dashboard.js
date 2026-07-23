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
