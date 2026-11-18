// Small progressive enhancements. Everything works without JavaScript.
(function () {
  // Scroll each hourly strip so the current hour (or the shift start) is visible.
  function focusStrips(root) {
    (root || document).querySelectorAll(".strip-wrap").forEach(function (wrap) {
      const target = wrap.querySelector(".hour--now") || wrap.querySelector(".hour:not(.hour--off)");
      if (!target || wrap.scrollWidth <= wrap.clientWidth) return;
      wrap.scrollLeft = Math.max(0, target.offsetLeft - wrap.offsetLeft - wrap.clientWidth / 3);
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    focusStrips();
  });
  document.addEventListener("htmx:afterSwap", function (event) {
    focusStrips(event.target.parentNode || document);
  });

  // Fill latitude and longitude from the phone's location on the site form.
  const button = document.querySelector("[data-locate]");
  if (!button) return;
  const status = document.querySelector("[data-locate-status]");
  button.addEventListener("click", function () {
    if (!navigator.geolocation) {
      status.textContent = button.dataset.unavailable || "Location is not available on this device.";
      return;
    }
    status.textContent = "…";
    navigator.geolocation.getCurrentPosition(
      function (position) {
        document.getElementById("id_latitude").value = position.coords.latitude.toFixed(4);
        document.getElementById("id_longitude").value = position.coords.longitude.toFixed(4);
        status.textContent = "✓";
      },
      function (error) {
        status.textContent = error.message;
      },
      { enableHighAccuracy: true, timeout: 15000 }
    );
  });
})();
