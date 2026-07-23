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
