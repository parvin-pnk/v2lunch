document.addEventListener('DOMContentLoaded', function() {
    // Remove item from cart
    document.addEventListener('click', function(e) {
        if (e.target.closest('.remove-from-cart')) {
            const button = e.target.closest('.remove-from-cart');
            const itemId = button.getAttribute('data-item-id');
            const itemType = button.getAttribute('data-item-type');
            const cartItem = button.closest('.cart-item');
            
            // Add loading state
            button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            button.disabled = true;
            
            fetch('/remove-from-cart', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({
                    item_id: itemId,
                    item_type: itemType
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Animate removal
                    cartItem.style.opacity = '0';
                    setTimeout(() => {
                        cartItem.remove();
                        
                        // Update cart count
                        const cartCount = document.querySelector('.navbar .badge');
                        if (cartCount) {
                            const newCount = parseInt(cartCount.textContent) - 1;
                            if (newCount > 0) {
                                cartCount.textContent = newCount;
                            } else {
                                cartCount.remove();
                                // Show empty cart state
                                document.querySelector('.modal-body').innerHTML = `
                                    <div class="empty-cart">
                                        <i class="fas fa-shopping-basket"></i>
                                        <p>Your cart is empty</p>
                                        <a href="${window.location.origin}" class="btn btn-outline-primary">
                                            Browse Menu
                                        </a>
                                    </div>
                                `;
                                // Hide checkout button
                                document.querySelector('.modal-footer a').remove();
                            }
                        }
                        
                        // Update subtotal
                        if (data.subtotal !== undefined) {
                            const subtotalElement = document.querySelector('.cart-summary span:last-child');
                            if (subtotalElement) {
                                subtotalElement.textContent = '$' + data.subtotal.toFixed(2);
                                // Update total
                                const totalElement = document.querySelector('.cart-summary .fw-bold span:last-child');
                                if (totalElement) {
                                    totalElement.textContent = '$' + (data.subtotal + 2.00).toFixed(2);
                                }
                            }
                        }
                    }, 300);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                button.innerHTML = '<i class="fas fa-trash-alt"></i>';
                button.disabled = false;
            });
        }
    });
});