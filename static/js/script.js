document.addEventListener('DOMContentLoaded', function() {
    // Quantity input validation
    document.querySelectorAll('input[type="number"]').forEach(input => {
        input.addEventListener('change', function() {
            if (this.value < 1) {
                this.value = 1;
            }
        });
    });
    
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelector(this.getAttribute('href')).scrollIntoView({
                behavior: 'smooth'
            });
        });
    });
});
// Add this to your script.js or in a <script> tag
document.addEventListener('DOMContentLoaded', function() {
    const toastContainer = document.querySelector('.toast-container');
    if (toastContainer) {
        const toasts = toastContainer.querySelectorAll('.toast');
        const maxToasts = 3; // Show maximum 3 notifications
        
        if (toasts.length > maxToasts) {
            for (let i = maxToasts; i < toasts.length; i++) {
                toasts[i].style.display = 'none';
            }
        }
    }
});
// Confirm order cancellation
document.querySelectorAll('.cancel-order-btn').forEach(button => {
    button.addEventListener('click', (e) => {
        if (!confirm('Are you sure you want to cancel this order?')) {
            e.preventDefault();
        }
    });
});
function dismissAnnouncement(announcementId) {
    const announcement = document.getElementById(`announcement-${announcementId}`);
    
    // Add slide-up animation
    announcement.style.transition = 'transform 0.3s ease-out, opacity 0.3s ease-out';
    announcement.style.transform = 'translateY(-100%)';
    announcement.style.opacity = '0';
    
    // After animation completes, remove element and send dismissal to server
    setTimeout(() => {
        announcement.remove();
        
        fetch('/dismiss_announcement', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `announcement_id=${announcementId}`
        }).catch(error => console.error('Error dismissing announcement:', error));
    }, 300);
}