document.addEventListener("DOMContentLoaded", function () {
    const rows = document.querySelectorAll(".clickable-row");
    rows.forEach(row => {
      row.addEventListener("click", () => {
        const href = row.getAttribute("data-href");
        if (href) {
          window.location.href = href;
        }
      });
    });
  });
  

  document.addEventListener("DOMContentLoaded", () => {
    const ctx = document.getElementById('ratingChart');

    if (!ctx) return;

    const ratingData = JSON.parse(document.getElementById("ratingData").textContent);

    const labels = ratingData.map(r => `#${r.match}`);
    const mus = ratingData.map(r => r.mu);
    const lower = ratingData.map(r => r.mu - r.sigma);
    const upper = ratingData.map(r => r.mu + r.sigma);

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Rating (μ)",
                    data: mus,
                    borderColor: "#3498db",
                    backgroundColor: "rgba(52, 152, 219, 0.1)",
                    tension: 0.3,
                    fill: true,
                    pointRadius: 4,
                },
                {
                    label: "Upper Bound (μ + σ)",
                    data: upper,
                    borderColor: "rgba(0,0,0,0)",
                    fill: '-1',
                    backgroundColor: "rgba(52, 152, 219, 0.05)",
                },
                {
                    label: "Lower Bound (μ - σ)",
                    data: lower,
                    borderColor: "rgba(0,0,0,0)",
                    fill: false,
                }
            ]
        },
        options: {
            responsive: true,
            scales: {
                y: { beginAtZero: false }
            }
        }
    });
});

