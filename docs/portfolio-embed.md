# Portfolio integration

Streamlit's supported embed parameter removes its toolbar and outer padding. PhotoCull uses
a separate **compact=true** flag to hide its repeated mode cards/eyebrow/footer and reduce
margins. Streamlit reserves embed and embed_options and does not expose them through
st.query_params. Use both parameters:

```html
<iframe
  src="https://YOUR-APP.streamlit.app/?embed=true&amp;compact=true"
  title="PhotoCull temporary photo analysis demo"
  width="100%"
  height="900"
  style="display:block;max-width:100%;border:0;border-radius:16px;"
  loading="lazy"
></iframe>
<p>
  <a href="https://YOUR-APP.streamlit.app/" target="_blank" rel="noopener noreferrer">
    Open Full Demo
  </a>
</p>
```

Keep vertical scrolling enabled. The main upload/results/privacy workflow remains available.
Use a public app; Streamlit does not officially support embedding private apps. The official
[embed guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app/embed-your-app)
documents the supported parameters. No CSS removes security controls or disables protections.
The styling layer uses a few Streamlit test IDs for card/margin decoration; review those after
framework upgrades, since they are not a permanent styling API.

Phase 7 checks the compact URL and a local iframe. The eventual portfolio origin, Cloud
cookies/headers and public uploads must be smoke-tested after deployment.
