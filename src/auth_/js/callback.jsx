import { ClerkProvider, useUser } from "@clerk/clerk-react";
import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";

const el = document.getElementById("clerk-callback");
const { publishableKey, callbackUrl } = el.dataset;

// Clerk initializes on mount, which exchanges any __clerk_db_jwt or
// __clerk_handshake token and sets the __session cookie. Once isLoaded
// is true the exchange is complete and we can return to the callback view.
function Exchange() {
  const { isLoaded } = useUser();

  useEffect(() => {
    if (isLoaded) {
      window.location.replace(callbackUrl);
    }
  }, [isLoaded]);

  return null;
}

createRoot(el).render(
  <ClerkProvider publishableKey={publishableKey}>
    <Exchange />
  </ClerkProvider>,
);
