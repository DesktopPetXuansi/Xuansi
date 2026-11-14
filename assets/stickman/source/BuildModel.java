package com.desktopaipet.stickman;

import com.live2d.cubism.doc.model.CModelSource;
import com.live2d.cubism.doc.model.drawable.TextureState;
import com.live2d.cubism.doc.model.drawable.artMesh.CArtMeshForm;
import com.live2d.cubism.doc.model.drawable.artMesh.CArtMeshSource;
import com.live2d.cubism.doc.model.exporter.CMocExportFormat;
import com.live2d.cubism.doc.model.exporter.CMocExportSetting;
import com.live2d.cubism.doc.model.exporter.dD;
import com.live2d.cubism.doc.model.exporter.w;
import com.live2d.cubism.doc.model.extension.textureInput.CTextureInput_TextureAtlasRegion;
import com.live2d.cubism.doc.model.extension.textureInput.CTextureInputExtension;
import com.live2d.cubism.doc.model.id.CDrawableId;
import com.live2d.cubism.doc.model.id.CParameterId;
import com.live2d.cubism.doc.model.interpolator.KeyformGridSource;
import com.live2d.cubism.doc.model.param.CParameterSource;
import com.live2d.cubism.doc.model.texture.textureAtlas.CTextureAtlas;
import com.live2d.cubism.util.ClassRenameMap_Cubism;
import com.live2d.graphics.CImageResource;
import com.live2d.graphics.filter.CubismStaticFilterLibrary;
import com.live2d.serialize.ClassRenameMap_Core;
import com.live2d.type.CAffine;
import com.live2d.type.CFormGuid;
import com.live2d.type.CParameterGuid;
import java.io.Reader;
import java.awt.image.BufferedImage;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import javax.imageio.ImageIO;
import kotlin.Pair;
import org.json.simple.parser.JSONParser;

/** 使用本机 Cubism Editor 5.3.04 的类型制作工程，不捏造二进制模型。 */
public final class BuildModel {
    public static void main(String[] args) {
        try {
            build(Path.of(args[0]).toAbsolutePath());
            System.exit(0);
        } catch (Throwable error) {
            error.printStackTrace();
            System.exit(1);
        }
    }

    private static void build(Path directory) throws Exception {
        Path logs = directory.resolve("../../data/verification/stickman-build").normalize();
        Files.createDirectories(logs);
        System.setProperty("logsFilePath", logs.toString());
        System.setProperty("logFilename", logs.resolve("cubism.log").toString());
        ClassRenameMap_Core.INSTANCE.setupOnce();
        new ClassRenameMap_Cubism();
        CModelSource.Companion.c();
        CubismStaticFilterLibrary.INSTANCE.initFilter();
        System.out.println("[火柴人] 初始化本机编辑器类型");

        Map<?, ?> layout;
        try (Reader reader = Files.newBufferedReader(directory.resolve("source/mesh-layout.json"), StandardCharsets.UTF_8)) {
            layout = (Map<?, ?>) new JSONParser().parse(reader);
        }
        CModelSource model = CModelSource.Companion.b("循环挥手火柴人", 512, 768);
        CParameterSource wave = new CParameterSource();
        wave.setId(new CParameterId("ParamWave"));
        wave.setName("挥手");
        wave.setMinValue(-1f);
        wave.setMaxValue(1f);
        wave.setDefaultValue(0f);
        model.getParameterSourceSet().add(wave, 0);

        CTextureAtlas atlas = new CTextureAtlas(model, "火柴人图集", 512, 512);
        // PNG 解码通常返回 ABGR，编辑器缓存只支持这里使用的 ARGB 像素类型。
        BufferedImage texture = new BufferedImage(512, 512, BufferedImage.TYPE_INT_ARGB);
        var graphics = texture.createGraphics();
        graphics.drawImage(ImageIO.read(directory.resolve("textures/texture_00.png").toFile()), 0, 0, null);
        graphics.dispose();
        atlas.setCachedAtlasImage(new CImageResource(texture, false));
        atlas.setLockCachedAtlasImage(true);
        model.getTextureManager().addTextureAtlas(atlas, 0);
        int order = 0;
        for (Object object : (List<?>) layout.get("layers")) {
            Map<?, ?> layer = (Map<?, ?>) object;
            CArtMeshSource mesh = new CArtMeshSource(model);
            String id = (String) layer.get("id");
            mesh.setId(new CDrawableId(id));
            mesh.setLocalName(id);
            float[] vertices = pairs((List<?>) layer.get("vertices"));
            mesh.setPositions(vertices);
            mesh.setIndices(new int[] {0, 1, 2, 0, 2, 3});
            mesh.setUvs(pairs((List<?>) layer.get("uv")));
            mesh.setCulling(false);
            mesh.setVisible(true);
            var extension = new CTextureInputExtension(mesh);
            mesh.addExtension(extension, 0);
            var input = new CTextureInput_TextureAtlasRegion(extension, atlas);
            // 编辑器会重新计算 UV，必须保存图集像素到原画布的部件平移映射。
            List<?> bbox = (List<?>) layer.get("bbox");
            List<?> rect = (List<?>) layer.get("rect");
            CAffine mapping = new CAffine();
            mapping.translate(
                ((Number) bbox.get(0)).floatValue() - ((Number) rect.get(0)).floatValue(),
                ((Number) bbox.get(1)).floatValue() - ((Number) rect.get(1)).floatValue()
            );
            input.setAtlasLocalToCanvasTransform(mapping);
            extension.addTextureInput(input);
            extension.setCurrentTextureInputData(input);
            mesh.setTextureState(TextureState.TEXTURE_ATLAS);
            model.addParameterControllableSource(mesh);
            model.getRootPart().addChild(mesh, order);
            extension.updateArtMeshSourceUvs();

            // 只有右前臂建立三个旋转关键形，其余六个部件不随参数变形。
            if (id.equals("ArmRightForearm")) {
                List<CFormGuid> forms = new ArrayList<>();
                for (float value : new float[] {-1f, 0f, 1f}) {
                    CArtMeshForm form = new CArtMeshForm(mesh, order, 1f, rotate(vertices, value * 25f), mesh.getCoordType());
                    mesh.getKeyforms().add(form);
                    forms.add(form.getGuid());
                }
                List<Pair<CParameterGuid, float[]>> binding = List.of(new Pair<>(wave.getGuid(), new float[] {-1f, 0f, 1f}));
                // Kotlin 接口名 import 是 Java 关键字，反射仅用于调用这个绑定方法。
                KeyformGridSource.class.getMethod("import", CModelSource.class, List.class, List.class)
                    .invoke(mesh.getKeyformGridSource(), model, binding, forms);
            } else {
                CArtMeshForm form = new CArtMeshForm(mesh, order, 1f, vertices.clone(), mesh.getCoordType());
                mesh.getKeyforms().add(form);
                mesh.getKeyformGridSource().setInitialKeyform(form.getGuid());
            }
            System.out.println("[火柴人] 已建立网格：" + id + "，坐标类型=" + mesh.getCoordType());
            order++;
        }
        model.setup();
        model.verify(true, new com.live2d.util.verify.a());
        Path project = directory.resolve("source/stickman.cmo3");
        if (!model.saveModel(project.toFile(), false)) throw new IllegalStateException("Cubism 工程保存失败");
        System.out.println("[火柴人] 已保存可编辑工程：" + project);

        // 从保存后的工程重新载入再导出，确认交付工程保留纹理和参数绑定。
        CModelSource saved = CModelSource.Companion.a(project.toFile(), false);
        CMocExportSetting setting = new CMocExportSetting();
        setting.setExportFormat(CMocExportFormat.V5_00_00);
        setting.setOriginX(256f);
        setting.setOriginY(384f);
        setting.setPixelsPerUnit(768f);
        setting.setEnableExtendEdgeColor(false);
        w exporter = new w();
        exporter.a(setting);
        dD result = exporter.a(saved, null);
        byte[] bytes = new byte[result.a().size()];
        for (int i = 0; i < bytes.length; i++) bytes[i] = result.a().get(i);
        if (bytes.length < 64 || bytes[0] != 'M' || bytes[1] != 'O' || bytes[2] != 'C' || bytes[3] != '3') {
            throw new IllegalStateException("导出数据不是有效的 MOC3 文件");
        }
        Files.write(directory.resolve("stickman.moc3"), bytes);
        System.out.println("[火柴人] 已导出 SDK 5.0 模型，字节数=" + bytes.length + "，图集数=" + result.b().size());
    }

    private static float[] pairs(List<?> points) {
        float[] result = new float[points.size() * 2];
        for (int i = 0; i < points.size(); i++) {
            List<?> point = (List<?>) points.get(i);
            result[i * 2] = ((Number) point.get(0)).floatValue();
            result[i * 2 + 1] = ((Number) point.get(1)).floatValue();
        }
        return result;
    }

    private static float[] rotate(float[] vertices, float degrees) {
        float[] result = vertices.clone();
        double angle = Math.toRadians(degrees);
        double cosine = Math.cos(angle);
        double sine = Math.sin(angle);
        for (int i = 0; i < result.length; i += 2) {
            double x = vertices[i] - 343f;
            double y = vertices[i + 1] - 287f;
            result[i] = (float) (343 + cosine * x - sine * y);
            result[i + 1] = (float) (287 + sine * x + cosine * y);
        }
        return result;
    }
}
