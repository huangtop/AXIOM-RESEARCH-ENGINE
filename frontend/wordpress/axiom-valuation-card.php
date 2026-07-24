<?php
/** AXIOM V026.1 Research Bundle valuation card shortcode. */
if (!defined('ABSPATH')) { exit; }

if (!defined('AXIOM_RESEARCH_CARD_API_BASE')) {
    define('AXIOM_RESEARCH_CARD_API_BASE', 'http://127.0.0.1:8766');
}

function axiom_v0261_register_assets() {
    $base = plugin_dir_url(__FILE__) . '../';
    wp_register_style('axiom-v0261-card', $base . 'axiom-valuation-card.css', array(), '26.1.0');
    wp_register_script('axiom-v0261-card', $base . 'axiom-valuation-card.js', array(), '26.1.0', true);
}
add_action('wp_enqueue_scripts', 'axiom_v0261_register_assets');

function axiom_v0261_shortcode($atts = array()) {
    $atts = shortcode_atts(array('ticker' => 'NVDA'), $atts, 'axiom_valuation');
    $ticker = strtoupper(sanitize_text_field($atts['ticker']));
    wp_enqueue_style('axiom-v0261-card');
    wp_enqueue_script('axiom-v0261-card');
    ob_start(); ?>
    <div class="axiom-valuation-card" data-axiom-valuation-card
         data-endpoint="<?php echo esc_attr(untrailingslashit(AXIOM_RESEARCH_CARD_API_BASE) . '/v1/research/valuation-card'); ?>"
         data-initial-ticker="<?php echo esc_attr($ticker); ?>">
      <form class="axiom-search" data-axiom-form>
        <input data-axiom-ticker value="<?php echo esc_attr($ticker); ?>" maxlength="16" autocomplete="off" aria-label="Ticker">
        <button type="submit">載入研究卡</button>
      </form>
      <div data-axiom-output aria-live="polite"></div>
    </div>
    <?php return ob_get_clean();
}

if (shortcode_exists('axiom_valuation')) { remove_shortcode('axiom_valuation'); }
add_shortcode('axiom_valuation', 'axiom_v0261_shortcode');
