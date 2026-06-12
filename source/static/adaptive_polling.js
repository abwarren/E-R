/**
 * Adaptive Polling Library
 * Reusable across Engine, Collector, and Remote Control UIs
 * 
 * Features:
 * - Smart polling (fast when active, slow when idle)
 * - Exponential backoff on errors
 * - Page visibility handling (pause when hidden)
 * - Manual pause/resume
 * - Observable state
 */

class AdaptivePoller {
  constructor(options = {}) {
    // Configuration
    this.fastPoll = options.fastPoll || 1500;       // Active: 1.5s
    this.slowPoll = options.slowPoll || 5000;       // Idle: 5s
    this.idleThreshold = options.idleThreshold || 30000;  // 30s no change = idle
    this.maxRetryDelay = options.maxRetryDelay || 30000;  // Max 30s backoff
    this.timeout = options.timeout || 10000;        // 10s request timeout
    this.enableVisibilityPause = options.enableVisibilityPause !== false;
    
    // State
    this.currentInterval = this.fastPoll;
    this.lastDataChange = Date.now();
    this.lastDataHash = null;
    this.consecutiveErrors = 0;
    this.isPaused = false;
    this.pollTimer = null;
    
    // Callbacks
    this.onPoll = options.onPoll || (() => Promise.resolve(null));
    this.onChange = options.onChange || (() => {});
    this.onError = options.onError || ((err) => console.error('[POLL] Error:', err));
    this.onStateChange = options.onStateChange || (() => {});
    
    // Bind visibility handler
    if (this.enableVisibilityPause) {
      this._handleVisibilityChange = this._handleVisibilityChange.bind(this);
      if (document.addEventListener) {
        document.addEventListener('visibilitychange', this._handleVisibilityChange);
      }
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  // PUBLIC API
  // ════════════════════════════════════════════════════════════════════════

  start() {
    if (this.pollTimer) return;
    this.isPaused = false;
    this._poll();
    console.log(`[POLL] Started: Fast=${this.fastPoll}ms, Slow=${this.slowPoll}ms, Idle=${this.idleThreshold/1000}s`);
  }

  stop() {
    this._clearTimer();
    console.log('[POLL] Stopped');
  }

  pause() {
    this.isPaused = true;
    this._clearTimer();
    console.log('[POLL] Paused');
  }

  resume() {
    if (!this.isPaused) return;
    this.isPaused = false;
    console.log('[POLL] Resumed');
    this._poll();
  }

  getState() {
    return {
      interval: this.currentInterval,
      timeSinceChange: Date.now() - this.lastDataChange,
      isIdle: (Date.now() - this.lastDataChange) > this.idleThreshold,
      isPaused: this.isPaused,
      consecutiveErrors: this.consecutiveErrors,
      lastDataHash: this.lastDataHash
    };
  }

  destroy() {
    this.stop();
    if (this.enableVisibilityPause && document.removeEventListener) {
      document.removeEventListener('visibilitychange', this._handleVisibilityChange);
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  // INTERNAL METHODS
  // ════════════════════════════════════════════════════════════════════════

  _clearTimer() {
    if (this.pollTimer) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
  }

  _calculateBackoff() {
    // Exponential backoff: 2s, 4s, 8s, 16s, max 30s
    return Math.min(2000 * Math.pow(2, this.consecutiveErrors), this.maxRetryDelay);
  }

  _scheduleNext() {
    if (this.isPaused) return;
    
    const delay = this.consecutiveErrors > 0 
      ? this._calculateBackoff() 
      : this.currentInterval;
    
    this.pollTimer = setTimeout(() => this._poll(), delay);
  }

  _adjustSpeed() {
    const timeSinceChange = Date.now() - this.lastDataChange;
    const shouldBeIdle = timeSinceChange > this.idleThreshold;
    const targetInterval = shouldBeIdle ? this.slowPoll : this.fastPoll;

    if (targetInterval !== this.currentInterval) {
      const wasIdle = this.currentInterval === this.slowPoll;
      this.currentInterval = targetInterval;
      
      const mode = shouldBeIdle ? 'IDLE' : 'ACTIVE';
      console.log(`[POLL] Speed: ${mode} (${this.currentInterval}ms)`);
      
      this.onStateChange({ interval: this.currentInterval, mode, wasIdle });
    }
  }

  _handleVisibilityChange() {
    if (document.hidden) {
      this.pause();
      console.log('[POLL] Tab hidden');
    } else {
      this.resume();
      console.log('[POLL] Tab visible');
    }
  }

  async _poll() {
    if (this.isPaused) return;

    try {
      // Call user-provided poll function
      const data = await this.onPoll();
      
      // Success - reset error counter
      if (this.consecutiveErrors > 0) {
        console.log('[POLL] Connection restored');
        this.consecutiveErrors = 0;
      }

      // Check if data changed
      const currentHash = this._hashData(data);
      const hasChanged = currentHash !== this.lastDataHash;

      if (hasChanged) {
        this.lastDataHash = currentHash;
        this.lastDataChange = Date.now();
        
        // Notify change callback
        this.onChange(data, currentHash);
      }

      // Adjust poll speed
      this._adjustSpeed();

    } catch (err) {
      this.consecutiveErrors++;
      const backoff = this._calculateBackoff();
      
      console.error(`[POLL] Failed (${this.consecutiveErrors}x): ${err.message}, retry in ${backoff}ms`);
      this.onError(err, this.consecutiveErrors, backoff);
      
    } finally {
      this._scheduleNext();
    }
  }

  _hashData(data) {
    if (!data) return null;
    try {
      return typeof data === 'string' 
        ? data.trim() 
        : JSON.stringify(data);
    } catch (e) {
      console.error('[POLL] Hash error:', e);
      return String(Date.now());
    }
  }
}

// Export for browser use
if (typeof window !== 'undefined') {
  window.AdaptivePoller = AdaptivePoller;
}

// Export for Node.js (if needed for testing)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = AdaptivePoller;
}
