// Intentionally vulnerable training fixture; do not copy into production.
const express = require("express");
const app = express();

app.get("/redirect", (req, res) => {
  res.redirect(req.query.url);
});

module.exports = app;
