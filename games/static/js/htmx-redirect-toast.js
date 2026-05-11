(function() {
  htmx.defineExtension("hx-redirect-toast", {
    isInlineSwap: function(swapStyle) {
      return swapStyle === "hx-redirect-toast";
    },
    handleSwap: function(swapStyle, target, fragment, settleInfo, htmxConfig) {
      var xhr = htmxConfig.xhr;
      var hxRedirect = xhr.getResponseHeader("HX-Redirect");
      var hxTrigger = xhr.getResponseHeader("HX-Trigger");

      // Redirect immediately (toast will be shown on the new page)
      if (hxRedirect) {
        window.location.href = hxRedirect;
      }

      // Only dispatch HX-Trigger events for toasts when not redirecting
      if (!hxRedirect && hxTrigger) {
        var triggers = JSON.parse(hxTrigger);
        var events = Array.isArray(triggers) ? triggers : [triggers];
        events.forEach(function(triggerObj) {
          Object.entries(triggerObj).forEach(function(entry) {
            var name = entry[0];
            var detail = entry[1];
            try { detail = JSON.parse(detail); } catch(e) {}
            target.dispatchEvent(new CustomEvent(name, {
              detail: detail,
              bubbles: true,
              cancelable: true
            }));
          });
        });
      }
      // Return null to prevent any DOM swap
      return null;
    }
  });
})();
