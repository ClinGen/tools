import { ClerkProvider, SignIn, useUser } from "@clerk/clerk-react";
import React, { useEffect } from "react";
import { createRoot } from "react-dom/client";

const el = document.getElementById("clerk-sign-in");
const { publishableKey, callbackUrl } = el.dataset;

function App() {
  const { isLoaded, isSignedIn } = useUser();

  useEffect(() => {
    if (isLoaded && isSignedIn) {
      window.location.replace(callbackUrl);
    }
  }, [isLoaded, isSignedIn]);

  if (!isLoaded || isSignedIn) return null;

  return <SignIn forceRedirectUrl={callbackUrl} />;
}

createRoot(el).render(
  <ClerkProvider publishableKey={publishableKey}>
    <App />
  </ClerkProvider>,
);
