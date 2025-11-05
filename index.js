// index.js
import fs from "fs";
import path from "path";
import {
  Client,
  GatewayIntentBits,
  REST,
  Routes,
  EmbedBuilder,
  ChannelType,
  PermissionFlagsBits,
} from "discord.js";

const root = process.cwd();
const cfgPath = path.join(root, "config.json");
const stockPath = path.join(root, "stock.json");
const statePath = path.join(root, "state.json");
const pkgPath = path.join(root, "package.json");
const logsDir = path.join(root, "logs");

// --- Helper: synchronous safe file utils ---
function writeIfMissing(p, contents) {
  if (fs.existsSync(p)) return false;
  fs.writeFileSync(p, contents, { encoding: "utf8" });
  return true;
}

function safeReadJSON(p, fallback = {}) {
  try {
    if (!fs.existsSync(p)) {
      fs.writeFileSync(p, JSON.stringify(fallback, null, 2), "utf8");
      return fallback;
    }
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (err) {
    console.error(`Error reading JSON ${p}:`, err);
    return fallback;
  }
}

function safeWriteJSON(p, data) {
  try {
    fs.writeFileSync(p, JSON.stringify(data, null, 2), "utf8");
    return true;
  } catch (err) {
    console.error(`Error writing JSON ${p}:`, err);
    return false;
  }
}

// --- Create missing files / folders (non-destructive) ---
const created = [];
if (!fs.existsSync(logsDir)) {
  fs.mkdirSync(logsDir, { recursive: true });
  created.push("logs/");
}

// package.json default (only create if missing)
const defaultPkg = {
  name: "stock-keeper-bot",
  version: "1.0.0",
  description: "Discord bot to manage virtual product stock",
  main: "index.js",
  type: "module",
  scripts: { start: "node index.js" },
  dependencies: { "discord.js": "^14.16.0" }
};
if (writeIfMissing(pkgPath, JSON.stringify(defaultPkg, null, 2))) created.push("package.json");

// stock.json default products (create if missing)
const defaultStock = {
  "Hex Lifetime": 0,
  "Hex Monthly": 0,
  "SRC Lifetime": 0,
  "SRC Monthly": 1
};
if (writeIfMissing(stockPath, JSON.stringify(defaultStock, null, 2))) created.push("stock.json");

// state.json default (create if missing)
const defaultState = { stockMessageId: null };
if (writeIfMissing(statePath, JSON.stringify(defaultState, null, 2))) created.push("state.json");

// config.json template (do NOT auto-fill token with a real token)
// If config is missing, create a template and exit so user can fill it.
const configTemplate = {
  token: "YOUR_BOT_TOKEN_HERE",
  clientId: "YOUR_BOT_CLIENT_ID",
  guildId: "YOUR_GUILD_ID",
  stockChannelId: "CHANNEL_ID_FOR_STOCK_MESSAGE",
  authorizedRoles: ["ROLE_ID_1", "ROLE_ID_2"],
  ticketCategoryId: "TICKET_CATEGORY_ID",
  alertUserId: "YOUR_DISCORD_USER_ID",
  debug: true
};
let createdConfigTemplate = false;
if (!fs.existsSync(cfgPath)) {
  fs.writeFileSync(cfgPath, JSON.stringify(configTemplate, null, 2), "utf8");
  created.push("config.json (TEMPLATE)");
  createdConfigTemplate = true;
}

// Inform user of created files
if (created.length) {
  console.log("Created missing files/folders:", created.join(", "));
  if (createdConfigTemplate) {
    console.log("\nIMPORTANT: A template config.json was created. Open it, fill in your bot token, clientId, guildId, IDs, then restart this bot.\n");
    process.exit(0); // stop now so user can fill in the token before the bot tries to login
  }
}

// Load config/stock/state (they should exist now)
const config = safeReadJSON(cfgPath, configTemplate);
const stock = safeReadJSON(stockPath, defaultStock);
const state = safeReadJSON(statePath, defaultState);

const debug = Boolean(config.debug);
const log = (...args) => { if (debug) console.log(`[${new Date().toISOString()}]`, ...args); };

// Basic validation of config values
function isPlaceholder(v) {
  if (!v || typeof v !== "string") return true;
  const placeholders = ["YOUR_BOT_TOKEN", "YOUR_BOT_CLIENT_ID", "YOUR_GUILD_ID", "CHANNEL_ID_FOR_STOCK_MESSAGE", "TICKET_CATEGORY_ID", "YOUR_DISCORD_USER_ID"];
  return placeholders.some(p => v.includes(p) || v === "");
}

if (!config.token || isPlaceholder(config.token) || !config.clientId || isPlaceholder(config.clientId) || !config.guildId || isPlaceholder(config.guildId)) {
  console.error("config.json is missing required fields or still contains placeholder values. Edit config.json and restart.");
  process.exit(1);
}

// --- Helpers used by bot ---
function ensureProduct(name) {
  if (!name) return;
  if (stock[name] === undefined) {
    stock[name] = 0;
    safeWriteJSON(stockPath, stock);
    log("Added missing product to stock.json:", name);
  }
}

function generateStockEmbed() {
  const embed = new EmbedBuilder()
    .setTitle("📦 Product Stock")
    .setColor("#00AAFF")
    .setDescription("Live product availability — updated automatically.")
    .setTimestamp();

  embed.addFields(
    {
      name: "《Hex:》",
      value: [
        `Lifetime — ${stock["Hex Lifetime"] > 0 ? "🟢 In Stock — **$80**" : "🔴 Out of Stock — **$80**"}`,
        `Monthly — ${stock["Hex Monthly"] > 0 ? "🟢 In Stock — **$13**" : "🔴 Out of Stock — **$13**"}`
      ].join("\n"),
      inline: false
    },
    {
      name: "《SRC:》",
      value: [
        `Lifetime — ${stock["SRC Lifetime"] > 0 ? "🟢 In Stock — **$65**" : "🔴 Out of Stock — **$65**"}`,
        `Monthly — ${stock["SRC Monthly"] > 0 ? "🟢 In Stock — **$12**" : "🔴 Out of Stock — **$12**"}`
      ].join("\n"),
      inline: false
    }
  );

  return embed;
}

function safeWriteAllState() {
  safeWriteJSON(stockPath, stock);
  safeWriteJSON(statePath, state);
}

// --- Discord client and commands (unchanged core features) ---
const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMembers],
  failIfNotExists: false,
});

// Commands array (guild-scoped)
const commands = [
  { name: "addstock", description: "Add stock to a product.", options: [{ name: "product", type: 3, required: true }, { name: "amount", type: 4, required: true }] },
  { name: "removestock", description: "Remove stock from a product.", options: [{ name: "product", type: 3, required: true }, { name: "amount", type: 4, required: true }] },
  { name: "setstock", description: "Set stock for a product.", options: [{ name: "product", type: 3, required: true }, { name: "amount", type: 4, required: true }] },
  { name: "restockmessage", description: "Create or refresh the persistent stock message in the stock channel." },
  { name: "liststock", description: "List all stock statuses (ephemeral)." },
  { name: "getstatus", description: "Get a single product's status.", options: [{ name: "product", type: 3, required: true }] },
  { name: "resetstock", description: "Reset all stock to 0 (admin-only)." }
];

async function registerCommands() {
  try {
    if (!config.clientId || !config.guildId) {
      log("clientId or guildId missing in config; skipping command registration.");
      return;
    }
    const rest = new REST({ version: "10" }).setToken(config.token);
    await rest.put(Routes.applicationGuildCommands(config.clientId, config.guildId), { body: commands });
    log("Slash commands registered.");
  } catch (err) {
    console.error("Failed to register commands:", err);
  }
}

async function updateStockMessage() {
  try {
    if (!state.stockMessageId) {
      log("No persisted stock message ID; use /restockmessage to create one.");
      return;
    }
    const channel = await client.channels.fetch(config.stockChannelId).catch(() => null);
    if (!channel) {
      log("Stock channel not found (check stockChannelId).");
      return;
    }
    if (![ChannelType.GuildText, ChannelType.GuildAnnouncement].includes(channel.type)) {
      log("Configured stock channel is not a text-based channel.");
      return;
    }
    const msg = await channel.messages.fetch(state.stockMessageId).catch(() => null);
    if (!msg) {
      log("Stored stock message not found. It may have been deleted. Run /restockmessage.");
      return;
    }
    await msg.edit({ embeds: [generateStockEmbed()] });
    log("Updated persistent stock message.");
  } catch (err) {
    console.error("Error updating stock message:", err);
  }
}

function hasAuthorizedRole(member) {
  try {
    if (!config.authorizedRoles || !Array.isArray(config.authorizedRoles) || config.authorizedRoles.length === 0) return false;
    return member.roles.cache.some(r => config.authorizedRoles.includes(r.id));
  } catch {
    return false;
  }
}

// Command handling
client.on("interactionCreate", async (interaction) => {
  try {
    if (!interaction.isChatInputCommand()) return;
    const command = interaction.commandName;
    const product = interaction.options.getString("product");
    const amount = interaction.options.getInteger("amount");
    const member = interaction.member;

    const adminOnly = ["addstock", "removestock", "setstock", "resetstock", "restockmessage"];
    if (adminOnly.includes(command) && !hasAuthorizedRole(member)) {
      return await interaction.reply({ content: "🚫 You are not authorized to use this command.", ephemeral: true });
    }

    if (command === "addstock") {
      ensureProduct(product);
      stock[product] = (stock[product] || 0) + Math.max(0, amount);
      safeWriteAllState();
      await updateStockMessage();
      return await interaction.reply({ content: `✅ Added ${amount} to **${product}**.`, ephemeral: true });
    }

    if (command === "removestock") {
      ensureProduct(product);
      stock[product] = Math.max(0, (stock[product] || 0) - Math.max(0, amount));
      safeWriteAllState();
      await updateStockMessage();
      return await interaction.reply({ content: `✅ Removed ${amount} from **${product}**.`, ephemeral: true });
    }

    if (command === "setstock") {
      ensureProduct(product);
      stock[product] = Math.max(0, amount);
      safeWriteAllState();
      await updateStockMessage();
      return await interaction.reply({ content: `✅ Set **${product}** stock to ${amount}.`, ephemeral: true });
    }

    if (command === "restockmessage") {
      const channel = await client.channels.fetch(config.stockChannelId).catch(() => null);
      if (!channel) return await interaction.reply({ content: "⚠️ Stock channel not found. Check config.", ephemeral: true });

      const me = await channel.guild.members.fetchMe();
      const perms = channel.permissionsFor(me);
      if (!perms || !perms.has([PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.EmbedLinks])) {
        return await interaction.reply({ content: "⚠️ Bot lacks required permissions in the configured stock channel (View, Send, Embed).", ephemeral: true });
      }

      const embed = generateStockEmbed();
      const msg = await channel.send({ embeds: [embed] });
      state.stockMessageId = msg.id;
      safeWriteAllState();
      return await interaction.reply({ content: "✅ Stock message created and saved persistently.", ephemeral: true });
    }

    if (command === "liststock") {
      const summary = Object.entries(stock).map(([k, v]) => `${k}: ${v > 0 ? "🟢 In Stock" : "🔴 Out of Stock"}`).join("\n") || "No products defined.";
      return await interaction.reply({ content: summary, ephemeral: true });
    }

    if (command === "getstatus") {
      if (stock[product] === undefined) return await interaction.reply({ content: "⚠️ Product not found. Make sure the name matches exactly.", ephemeral: true });
      return await interaction.reply({ content: `${product} — ${stock[product] > 0 ? "🟢 In Stock" : "🔴 Out of Stock"}`, ephemeral: true });
    }

    if (command === "resetstock") {
      for (const k of Object.keys(stock)) stock[k] = 0;
      safeWriteAllState();
      await updateStockMessage();
      return await interaction.reply({ content: "🧹 All stock reset to 0.", ephemeral: true });
    }
  } catch (err) {
    console.error("Command handling error:", err);
    try { if (interaction && !interaction.replied) await interaction.reply({ content: "⚠️ An error occurred. Check console logs.", ephemeral: true }); } catch {}
  }
});

// Ticket Tool listener: DM alert when Ticket Tool creates a channel in the configured category
client.on("channelCreate", async (channel) => {
  try {
    if (!config.ticketCategoryId) return;
    if (!channel || !channel.guild) return;
    if (channel.parentId !== config.ticketCategoryId) return;
    if (![ChannelType.GuildText, ChannelType.PublicThread, ChannelType.PrivateThread].includes(channel.type)) return;

    log("Detected new channel in ticket category:", channel.id, channel.name);

    const dmEmbed = new EmbedBuilder()
      .setTitle("🎟️ New Ticket Opened")
      .setDescription("A new ticket has been created in the server.")
      .addFields(
        { name: "Channel", value: `<#${channel.id}>`, inline: true },
        { name: "Channel Name", value: `${channel.name}`, inline: true }
      )
      .setTimestamp()
      .setColor("#00AAFF");

    const maybeId = (channel.name || "").match(/\d{17,19}/);
    if (maybeId) {
      try {
        const u = await client.users.fetch(maybeId[0]);
        if (u) dmEmbed.addFields({ name: "Opened By", value: `${u.tag} (${u.id})`, inline: true });
      } catch {
        dmEmbed.addFields({ name: "Opened By", value: `User ID ${maybeId[0]}`, inline: true });
      }
    }

    if (!config.alertUserId) {
      log("alertUserId not configured; skipping ticket DM.");
      return;
    }

    const alertUser = await client.users.fetch(config.alertUserId).catch(() => null);
    if (!alertUser) {
      log("Could not fetch alert user; they may have DMs disabled.");
      return;
    }

    await alertUser.send({ embeds: [dmEmbed] }).catch(err => {
      log("Failed to send DM to alert user (they may have DMs closed):", err?.message || err);
    });

    log(`DM alert attempted to ${config.alertUserId} about ticket ${channel.id}`);
  } catch (err) {
    console.error("Error in channelCreate handler:", err);
  }
});

// ready
client.once("ready", async () => {
  log(`Logged in as ${client.user.tag} (${client.user.id})`);
  await registerCommands();
  await updateStockMessage();
});

// global error capture
process.on("unhandledRejection", (err) => console.error("Unhandled rejection:", err));
client.login(config.token).catch(err => { console.error("Login failed - check token:", err); process.exit(1); });
