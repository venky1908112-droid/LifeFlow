/* LifeFlow BloodBank — Main JS */

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
}

document.addEventListener('click', function(e) {
  const sidebar = document.getElementById('sidebar');
  const toggle  = document.querySelector('.menu-toggle');
  if (sidebar && !sidebar.contains(e.target) && toggle && !toggle.contains(e.target)) {
    sidebar.classList.remove('open');
  }
});

// Animated counters (home page stats)
function animateCounters() {
  document.querySelectorAll('.stat-number[data-target]').forEach(counter => {
    const target = parseInt(counter.getAttribute('data-target'));
    const step   = Math.max(1, target / 60);
    let current  = 0;
    const timer  = setInterval(() => {
      current += step;
      if (current >= target) { counter.textContent = target; clearInterval(timer); }
      else { counter.textContent = Math.floor(current); }
    }, 16);
  });
}

const statsSection = document.getElementById('stats');
if (statsSection) {
  new IntersectionObserver((entries) => {
    entries.forEach(e => { if (e.isIntersecting) { animateCounters(); } });
  }, { threshold: 0.3 }).observe(statsSection);
}

// Auto-dismiss flash messages
setTimeout(() => {
  document.querySelectorAll('.flash').forEach(f => {
    f.style.transition = 'opacity 0.4s ease';
    f.style.opacity = '0';
    setTimeout(() => f.remove(), 400);
  });
}, 5000);

// Stock bar animations
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.stock-bar-fill, .bg-bar-fill').forEach(bar => {
    const w = bar.style.width;
    bar.style.width = '0';
    setTimeout(() => { bar.style.width = w; }, 150);
  });

  // Prevent duplicate form submissions
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', function() {
      const btn = this.querySelector('button[type="submit"]');
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Processing…';
        setTimeout(() => { btn.disabled = false; }, 6000); // re-enable after 6s as fallback
      }
    });
  });
});
