cuda_tile.module @m {
  entry @view_conv2d(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 0> : tile<i32>
    %8 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %9 = offset %8, %7 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %11 = make_partition_view %10 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %12 = constant <i32: 0> : tile<i32>
    %13 = reshape %12 : tile<i32> -> tile<1x1xi32>
    %14 = broadcast %13 : tile<1x1xi32> -> tile<16x16xi32>
    %15 = iota : tile<16xi32>
    %16 = reshape %15 : tile<16xi32> -> tile<16x1xi32>
    %17 = broadcast %16 : tile<16x1xi32> -> tile<16x16xi32>
    %18 = constant <i32: 0> : tile<16x16xi32>
    %19 = muli %17, %18 : tile<16x16xi32>
    %20 = addi %14, %19 : tile<16x16xi32>
    %21 = iota : tile<16xi32>
    %22 = reshape %21 : tile<16xi32> -> tile<1x16xi32>
    %23 = broadcast %22 : tile<1x16xi32> -> tile<16x16xi32>
    %24 = constant <i32: 0> : tile<16x16xi32>
    %25 = muli %23, %24 : tile<16x16xi32>
    %26 = addi %20, %25 : tile<16x16xi32>
    %27 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %28 = broadcast %27 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %29 = offset %28, %26 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %30, %31 = load_ptr_tko weak %29 token=%0 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %32, %33 = load_view_tko weak %11[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %34 = mulf %32, %30 rounding<nearest_even> : tile<16x16xf64>
    %35 = constant <f64: 0.0> : tile<16x16xf64>
    %36 = addf %35, %34 rounding<nearest_even> : tile<16x16xf64>
    %37 = constant <i32: 1> : tile<i32>
    %38 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %39 = offset %38, %37 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %40 = make_tensor_view %39, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %41 = make_partition_view %40 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %42 = constant <i32: 1> : tile<i32>
    %43 = reshape %42 : tile<i32> -> tile<1x1xi32>
    %44 = broadcast %43 : tile<1x1xi32> -> tile<16x16xi32>
    %45 = iota : tile<16xi32>
    %46 = reshape %45 : tile<16xi32> -> tile<16x1xi32>
    %47 = broadcast %46 : tile<16x1xi32> -> tile<16x16xi32>
    %48 = constant <i32: 0> : tile<16x16xi32>
    %49 = muli %47, %48 : tile<16x16xi32>
    %50 = addi %44, %49 : tile<16x16xi32>
    %51 = iota : tile<16xi32>
    %52 = reshape %51 : tile<16xi32> -> tile<1x16xi32>
    %53 = broadcast %52 : tile<1x16xi32> -> tile<16x16xi32>
    %54 = constant <i32: 0> : tile<16x16xi32>
    %55 = muli %53, %54 : tile<16x16xi32>
    %56 = addi %50, %55 : tile<16x16xi32>
    %57 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %58 = broadcast %57 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %59 = offset %58, %56 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %60, %61 = load_ptr_tko weak %59 token=%0 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %62, %63 = load_view_tko weak %41[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %64 = mulf %62, %60 rounding<nearest_even> : tile<16x16xf64>
    %65 = addf %36, %64 rounding<nearest_even> : tile<16x16xf64>
    %66 = constant <i32: 2> : tile<i32>
    %67 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %68 = offset %67, %66 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %69 = make_tensor_view %68, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %70 = make_partition_view %69 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %71 = constant <i32: 2> : tile<i32>
    %72 = reshape %71 : tile<i32> -> tile<1x1xi32>
    %73 = broadcast %72 : tile<1x1xi32> -> tile<16x16xi32>
    %74 = iota : tile<16xi32>
    %75 = reshape %74 : tile<16xi32> -> tile<16x1xi32>
    %76 = broadcast %75 : tile<16x1xi32> -> tile<16x16xi32>
    %77 = constant <i32: 0> : tile<16x16xi32>
    %78 = muli %76, %77 : tile<16x16xi32>
    %79 = addi %73, %78 : tile<16x16xi32>
    %80 = iota : tile<16xi32>
    %81 = reshape %80 : tile<16xi32> -> tile<1x16xi32>
    %82 = broadcast %81 : tile<1x16xi32> -> tile<16x16xi32>
    %83 = constant <i32: 0> : tile<16x16xi32>
    %84 = muli %82, %83 : tile<16x16xi32>
    %85 = addi %79, %84 : tile<16x16xi32>
    %86 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %87 = broadcast %86 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %88 = offset %87, %85 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %89, %90 = load_ptr_tko weak %88 token=%0 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %91, %92 = load_view_tko weak %70[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %93 = mulf %91, %89 rounding<nearest_even> : tile<16x16xf64>
    %94 = addf %65, %93 rounding<nearest_even> : tile<16x16xf64>
    %95 = constant <i32: 36> : tile<i32>
    %96 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %97 = offset %96, %95 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %98 = make_tensor_view %97, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %99 = make_partition_view %98 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %100 = constant <i32: 3> : tile<i32>
    %101 = reshape %100 : tile<i32> -> tile<1x1xi32>
    %102 = broadcast %101 : tile<1x1xi32> -> tile<16x16xi32>
    %103 = iota : tile<16xi32>
    %104 = reshape %103 : tile<16xi32> -> tile<16x1xi32>
    %105 = broadcast %104 : tile<16x1xi32> -> tile<16x16xi32>
    %106 = constant <i32: 0> : tile<16x16xi32>
    %107 = muli %105, %106 : tile<16x16xi32>
    %108 = addi %102, %107 : tile<16x16xi32>
    %109 = iota : tile<16xi32>
    %110 = reshape %109 : tile<16xi32> -> tile<1x16xi32>
    %111 = broadcast %110 : tile<1x16xi32> -> tile<16x16xi32>
    %112 = constant <i32: 0> : tile<16x16xi32>
    %113 = muli %111, %112 : tile<16x16xi32>
    %114 = addi %108, %113 : tile<16x16xi32>
    %115 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %116 = broadcast %115 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %117 = offset %116, %114 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %118, %119 = load_ptr_tko weak %117 token=%0 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %120, %121 = load_view_tko weak %99[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %122 = mulf %120, %118 rounding<nearest_even> : tile<16x16xf64>
    %123 = addf %94, %122 rounding<nearest_even> : tile<16x16xf64>
    %124 = constant <i32: 37> : tile<i32>
    %125 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %126 = offset %125, %124 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %127 = make_tensor_view %126, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %128 = make_partition_view %127 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %129 = constant <i32: 4> : tile<i32>
    %130 = reshape %129 : tile<i32> -> tile<1x1xi32>
    %131 = broadcast %130 : tile<1x1xi32> -> tile<16x16xi32>
    %132 = iota : tile<16xi32>
    %133 = reshape %132 : tile<16xi32> -> tile<16x1xi32>
    %134 = broadcast %133 : tile<16x1xi32> -> tile<16x16xi32>
    %135 = constant <i32: 0> : tile<16x16xi32>
    %136 = muli %134, %135 : tile<16x16xi32>
    %137 = addi %131, %136 : tile<16x16xi32>
    %138 = iota : tile<16xi32>
    %139 = reshape %138 : tile<16xi32> -> tile<1x16xi32>
    %140 = broadcast %139 : tile<1x16xi32> -> tile<16x16xi32>
    %141 = constant <i32: 0> : tile<16x16xi32>
    %142 = muli %140, %141 : tile<16x16xi32>
    %143 = addi %137, %142 : tile<16x16xi32>
    %144 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %145 = broadcast %144 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %146 = offset %145, %143 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %147, %148 = load_ptr_tko weak %146 token=%0 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %149, %150 = load_view_tko weak %128[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %151 = mulf %149, %147 rounding<nearest_even> : tile<16x16xf64>
    %152 = addf %123, %151 rounding<nearest_even> : tile<16x16xf64>
    %153 = constant <i32: 38> : tile<i32>
    %154 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %155 = offset %154, %153 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %156 = make_tensor_view %155, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %157 = make_partition_view %156 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %158 = constant <i32: 5> : tile<i32>
    %159 = reshape %158 : tile<i32> -> tile<1x1xi32>
    %160 = broadcast %159 : tile<1x1xi32> -> tile<16x16xi32>
    %161 = iota : tile<16xi32>
    %162 = reshape %161 : tile<16xi32> -> tile<16x1xi32>
    %163 = broadcast %162 : tile<16x1xi32> -> tile<16x16xi32>
    %164 = constant <i32: 0> : tile<16x16xi32>
    %165 = muli %163, %164 : tile<16x16xi32>
    %166 = addi %160, %165 : tile<16x16xi32>
    %167 = iota : tile<16xi32>
    %168 = reshape %167 : tile<16xi32> -> tile<1x16xi32>
    %169 = broadcast %168 : tile<1x16xi32> -> tile<16x16xi32>
    %170 = constant <i32: 0> : tile<16x16xi32>
    %171 = muli %169, %170 : tile<16x16xi32>
    %172 = addi %166, %171 : tile<16x16xi32>
    %173 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %174 = broadcast %173 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %175 = offset %174, %172 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %176, %177 = load_ptr_tko weak %175 token=%0 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %178, %179 = load_view_tko weak %157[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %180 = mulf %178, %176 rounding<nearest_even> : tile<16x16xf64>
    %181 = addf %152, %180 rounding<nearest_even> : tile<16x16xf64>
    %182 = constant <i32: 72> : tile<i32>
    %183 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %184 = offset %183, %182 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %185 = make_tensor_view %184, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %186 = make_partition_view %185 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %187 = constant <i32: 6> : tile<i32>
    %188 = reshape %187 : tile<i32> -> tile<1x1xi32>
    %189 = broadcast %188 : tile<1x1xi32> -> tile<16x16xi32>
    %190 = iota : tile<16xi32>
    %191 = reshape %190 : tile<16xi32> -> tile<16x1xi32>
    %192 = broadcast %191 : tile<16x1xi32> -> tile<16x16xi32>
    %193 = constant <i32: 0> : tile<16x16xi32>
    %194 = muli %192, %193 : tile<16x16xi32>
    %195 = addi %189, %194 : tile<16x16xi32>
    %196 = iota : tile<16xi32>
    %197 = reshape %196 : tile<16xi32> -> tile<1x16xi32>
    %198 = broadcast %197 : tile<1x16xi32> -> tile<16x16xi32>
    %199 = constant <i32: 0> : tile<16x16xi32>
    %200 = muli %198, %199 : tile<16x16xi32>
    %201 = addi %195, %200 : tile<16x16xi32>
    %202 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %203 = broadcast %202 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %204 = offset %203, %201 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %205, %206 = load_ptr_tko weak %204 token=%0 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %207, %208 = load_view_tko weak %186[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %209 = mulf %207, %205 rounding<nearest_even> : tile<16x16xf64>
    %210 = addf %181, %209 rounding<nearest_even> : tile<16x16xf64>
    %211 = constant <i32: 73> : tile<i32>
    %212 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %213 = offset %212, %211 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %214 = make_tensor_view %213, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %215 = make_partition_view %214 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %216 = constant <i32: 7> : tile<i32>
    %217 = reshape %216 : tile<i32> -> tile<1x1xi32>
    %218 = broadcast %217 : tile<1x1xi32> -> tile<16x16xi32>
    %219 = iota : tile<16xi32>
    %220 = reshape %219 : tile<16xi32> -> tile<16x1xi32>
    %221 = broadcast %220 : tile<16x1xi32> -> tile<16x16xi32>
    %222 = constant <i32: 0> : tile<16x16xi32>
    %223 = muli %221, %222 : tile<16x16xi32>
    %224 = addi %218, %223 : tile<16x16xi32>
    %225 = iota : tile<16xi32>
    %226 = reshape %225 : tile<16xi32> -> tile<1x16xi32>
    %227 = broadcast %226 : tile<1x16xi32> -> tile<16x16xi32>
    %228 = constant <i32: 0> : tile<16x16xi32>
    %229 = muli %227, %228 : tile<16x16xi32>
    %230 = addi %224, %229 : tile<16x16xi32>
    %231 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %232 = broadcast %231 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %233 = offset %232, %230 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %234, %235 = load_ptr_tko weak %233 token=%0 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %236, %237 = load_view_tko weak %215[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %238 = mulf %236, %234 rounding<nearest_even> : tile<16x16xf64>
    %239 = addf %210, %238 rounding<nearest_even> : tile<16x16xf64>
    %240 = constant <i32: 74> : tile<i32>
    %241 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %242 = offset %241, %240 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %243 = make_tensor_view %242, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %244 = make_partition_view %243 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %245 = constant <i32: 8> : tile<i32>
    %246 = reshape %245 : tile<i32> -> tile<1x1xi32>
    %247 = broadcast %246 : tile<1x1xi32> -> tile<16x16xi32>
    %248 = iota : tile<16xi32>
    %249 = reshape %248 : tile<16xi32> -> tile<16x1xi32>
    %250 = broadcast %249 : tile<16x1xi32> -> tile<16x16xi32>
    %251 = constant <i32: 0> : tile<16x16xi32>
    %252 = muli %250, %251 : tile<16x16xi32>
    %253 = addi %247, %252 : tile<16x16xi32>
    %254 = iota : tile<16xi32>
    %255 = reshape %254 : tile<16xi32> -> tile<1x16xi32>
    %256 = broadcast %255 : tile<1x16xi32> -> tile<16x16xi32>
    %257 = constant <i32: 0> : tile<16x16xi32>
    %258 = muli %256, %257 : tile<16x16xi32>
    %259 = addi %253, %258 : tile<16x16xi32>
    %260 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %261 = broadcast %260 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %262 = offset %261, %259 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %263, %264 = load_ptr_tko weak %262 token=%0 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %265, %266 = load_view_tko weak %244[%1, %5] token=%0 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %267 = mulf %265, %263 rounding<nearest_even> : tile<16x16xf64>
    %268 = addf %239, %267 rounding<nearest_even> : tile<16x16xf64>
    %269 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %270 = make_tensor_view %269, shape = [38, 34], strides = [34, 1] : tensor_view<38x34xf64, strides=[34, 1]>
    %271 = make_partition_view %270 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[34, 1]>, dim_map=[0, 1]>
    %272, %273, %274 = get_tile_block_id : tile<i32>
    %275, %276, %277 = get_tile_block_id : tile<i32>
    %278 = store_view_tko weak %268, %271[%272, %276] token=%0 : tile<16x16xf64>, partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[34, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
