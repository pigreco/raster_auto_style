<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!--
  TEMPLATE DINAMICO
  I valori degli <item> sono RELATIVI (0 = minimo del granulo, 1 = massimo).
  Il backend li riscala con: valore = min + rel * (max - min).
  Il template e' una QML valida: si puo' aprire e modificare in QGIS
  (impostando min 0 e max 1), purche' si mantengano le custom properties.
-->
<qgis version="3.34.0" styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0" minScale="1e+08" maxScale="0">
  <customproperties>
    <Option type="Map">
      <!-- attiva la valorizzazione dinamica -->
      <Option name="dynamic_minmax" type="QString" value="true"/>
      <!-- "minmax" = statistiche del COG; "percentile" = taglio cumulativo -->
      <Option name="dynamic_minmax_mode" type="QString" value="minmax"/>
      <Option name="dynamic_percentile_low" type="QString" value="2"/>
      <Option name="dynamic_percentile_high" type="QString" value="98"/>
    </Option>
  </customproperties>
  <pipe>
    <provider>
      <resampling enabled="false" maxOversampling="2" zoomedInResamplingMethod="nearestNeighbour" zoomedOutResamplingMethod="nearestNeighbour"/>
    </provider>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" nodataColor="" classificationMin="0" classificationMax="1">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>MinMax</limits>
        <extent>WholeRaster</extent>
        <statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower>
        <cumulativeCutUpper>0.98</cumulativeCutUpper>
        <stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <colorrampshader colorRampType="INTERPOLATED" classificationMode="2" clip="0" labelPrecision="4" minimumValue="0" maximumValue="1">
          <colorramp type="gradient" name="[source]">
            <Option type="Map">
              <Option name="color1" type="QString" value="43,15,76,255"/>
              <Option name="color2" type="QString" value="244,230,30,255"/>
              <Option name="discrete" type="QString" value="0"/>
              <Option name="rampType" type="QString" value="gradient"/>
              <Option name="stops" type="QString" value="0.111111;50,45,104,255:0.222222;57,75,132,255:0.333333;50,103,139,255:0.444444;39,131,140,255:0.555556;47,157,131,255:0.666667;74,182,112,255:0.777778;111,204,90,255:0.888889;177,217,60,255"/>
            </Option>
          </colorramp>
          <item alpha="255" value="0" label="0.0000" color="#2b0f4c"/>
          <item alpha="255" value="0.111111" label="0.1111" color="#322d68"/>
          <item alpha="255" value="0.222222" label="0.2222" color="#394b84"/>
          <item alpha="255" value="0.333333" label="0.3333" color="#32678b"/>
          <item alpha="255" value="0.444444" label="0.4444" color="#27838c"/>
          <item alpha="255" value="0.555556" label="0.5556" color="#2f9d83"/>
          <item alpha="255" value="0.666667" label="0.6667" color="#4ab670"/>
          <item alpha="255" value="0.777778" label="0.7778" color="#6fcc5a"/>
          <item alpha="255" value="0.888889" label="0.8889" color="#b1d93c"/>
          <item alpha="255" value="1" label="1.0000" color="#f4e61e"/>
          <rampLegendSettings useContinuousLegend="0" minimumLabel="" maximumLabel="" prefix="" suffix="" direction="0" orientation="1"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation colorizeOn="0" colorizeRed="255" colorizeGreen="128" colorizeBlue="128" colorizeStrength="100" grayscaleMode="0" saturation="0" invertColors="0"/>
    <rasterresampler maxOversampling="2"/>
    <resamplingStage>resamplingFilter</resamplingStage>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
