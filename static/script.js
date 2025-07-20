async function generateScript() {
    const prompt = document.getElementById('promptInput').value.trim();
    const progressIndicator = document.getElementById('progressIndicator');
    const scriptResults = document.getElementById('scriptResults');
    
    if (!prompt) {
        showAlert("Please describe your alternate ending", "error");
        return;
    }
    
    currentPrompt = prompt;
    navigateToStep(3);
    scriptResults.classList.add('hidden');
    
    // Show progressive loading messages
    const loadingMessages = [
        "Analyzing the original movie plot...",
        "Brainstorming creative alternatives...",
        "Crafting your unique ending...",
        "Finalizing the details..."
    ];
    
    let messageIndex = 0;
    const progressInterval = setInterval(() => {
        messageIndex = (messageIndex + 1) % loadingMessages.length;
        document.getElementById('progressMessage').textContent = loadingMessages[messageIndex];
        updateProgressBar(20 + (messageIndex * 20));
    }, 3000);
    
    try {
        const response = await fetch('/generate_script', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                movie: currentMovie, 
                prompt: currentPrompt 
            })
        });
        
        clearInterval(progressInterval);
        updateProgressBar(90);
        
        const data = await response.json();
        
        if (data.status === "success") {
            // ... existing success handling ...
        } else {
            // ... existing error handling ...
        }
    } catch (error) {
        clearInterval(progressInterval);
        // ... existing error handling ...
    }
}