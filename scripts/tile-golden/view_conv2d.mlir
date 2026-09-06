cuda_tile.module @m {
  entry @view_conv2d(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <f64: 0.0> : tile<16x16xf64>
    %8 = constant <i32: 0> : tile<i32>
    %9 = offset %arg0, %8 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
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
    %32, %33 = load_view_tko weak %11[%1, %5] token=%31 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %34 = mulf %32, %30 rounding<nearest_even> : tile<16x16xf64>
    %35 = addf %7, %34 rounding<nearest_even> : tile<16x16xf64>
    %36 = constant <i32: 1> : tile<i32>
    %37 = offset %arg0, %36 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %38 = make_tensor_view %37, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %39 = make_partition_view %38 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %40 = constant <i32: 1> : tile<i32>
    %41 = reshape %40 : tile<i32> -> tile<1x1xi32>
    %42 = broadcast %41 : tile<1x1xi32> -> tile<16x16xi32>
    %43 = iota : tile<16xi32>
    %44 = reshape %43 : tile<16xi32> -> tile<16x1xi32>
    %45 = broadcast %44 : tile<16x1xi32> -> tile<16x16xi32>
    %46 = constant <i32: 0> : tile<16x16xi32>
    %47 = muli %45, %46 : tile<16x16xi32>
    %48 = addi %42, %47 : tile<16x16xi32>
    %49 = iota : tile<16xi32>
    %50 = reshape %49 : tile<16xi32> -> tile<1x16xi32>
    %51 = broadcast %50 : tile<1x16xi32> -> tile<16x16xi32>
    %52 = constant <i32: 0> : tile<16x16xi32>
    %53 = muli %51, %52 : tile<16x16xi32>
    %54 = addi %48, %53 : tile<16x16xi32>
    %55 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %56 = broadcast %55 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %57 = offset %56, %54 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %58, %59 = load_ptr_tko weak %57 token=%33 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %60, %61 = load_view_tko weak %39[%1, %5] token=%59 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %62 = mulf %60, %58 rounding<nearest_even> : tile<16x16xf64>
    %63 = addf %35, %62 rounding<nearest_even> : tile<16x16xf64>
    %64 = constant <i32: 2> : tile<i32>
    %65 = offset %arg0, %64 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %66 = make_tensor_view %65, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %67 = make_partition_view %66 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %68 = constant <i32: 2> : tile<i32>
    %69 = reshape %68 : tile<i32> -> tile<1x1xi32>
    %70 = broadcast %69 : tile<1x1xi32> -> tile<16x16xi32>
    %71 = iota : tile<16xi32>
    %72 = reshape %71 : tile<16xi32> -> tile<16x1xi32>
    %73 = broadcast %72 : tile<16x1xi32> -> tile<16x16xi32>
    %74 = constant <i32: 0> : tile<16x16xi32>
    %75 = muli %73, %74 : tile<16x16xi32>
    %76 = addi %70, %75 : tile<16x16xi32>
    %77 = iota : tile<16xi32>
    %78 = reshape %77 : tile<16xi32> -> tile<1x16xi32>
    %79 = broadcast %78 : tile<1x16xi32> -> tile<16x16xi32>
    %80 = constant <i32: 0> : tile<16x16xi32>
    %81 = muli %79, %80 : tile<16x16xi32>
    %82 = addi %76, %81 : tile<16x16xi32>
    %83 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %84 = broadcast %83 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %85 = offset %84, %82 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %86, %87 = load_ptr_tko weak %85 token=%61 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %88, %89 = load_view_tko weak %67[%1, %5] token=%87 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %90 = mulf %88, %86 rounding<nearest_even> : tile<16x16xf64>
    %91 = addf %63, %90 rounding<nearest_even> : tile<16x16xf64>
    %92 = constant <i32: 36> : tile<i32>
    %93 = offset %arg0, %92 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %94 = make_tensor_view %93, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %95 = make_partition_view %94 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %96 = constant <i32: 3> : tile<i32>
    %97 = reshape %96 : tile<i32> -> tile<1x1xi32>
    %98 = broadcast %97 : tile<1x1xi32> -> tile<16x16xi32>
    %99 = iota : tile<16xi32>
    %100 = reshape %99 : tile<16xi32> -> tile<16x1xi32>
    %101 = broadcast %100 : tile<16x1xi32> -> tile<16x16xi32>
    %102 = constant <i32: 0> : tile<16x16xi32>
    %103 = muli %101, %102 : tile<16x16xi32>
    %104 = addi %98, %103 : tile<16x16xi32>
    %105 = iota : tile<16xi32>
    %106 = reshape %105 : tile<16xi32> -> tile<1x16xi32>
    %107 = broadcast %106 : tile<1x16xi32> -> tile<16x16xi32>
    %108 = constant <i32: 0> : tile<16x16xi32>
    %109 = muli %107, %108 : tile<16x16xi32>
    %110 = addi %104, %109 : tile<16x16xi32>
    %111 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %112 = broadcast %111 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %113 = offset %112, %110 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %114, %115 = load_ptr_tko weak %113 token=%89 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %116, %117 = load_view_tko weak %95[%1, %5] token=%115 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %118 = mulf %116, %114 rounding<nearest_even> : tile<16x16xf64>
    %119 = addf %91, %118 rounding<nearest_even> : tile<16x16xf64>
    %120 = constant <i32: 37> : tile<i32>
    %121 = offset %arg0, %120 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %122 = make_tensor_view %121, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %123 = make_partition_view %122 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %124 = constant <i32: 4> : tile<i32>
    %125 = reshape %124 : tile<i32> -> tile<1x1xi32>
    %126 = broadcast %125 : tile<1x1xi32> -> tile<16x16xi32>
    %127 = iota : tile<16xi32>
    %128 = reshape %127 : tile<16xi32> -> tile<16x1xi32>
    %129 = broadcast %128 : tile<16x1xi32> -> tile<16x16xi32>
    %130 = constant <i32: 0> : tile<16x16xi32>
    %131 = muli %129, %130 : tile<16x16xi32>
    %132 = addi %126, %131 : tile<16x16xi32>
    %133 = iota : tile<16xi32>
    %134 = reshape %133 : tile<16xi32> -> tile<1x16xi32>
    %135 = broadcast %134 : tile<1x16xi32> -> tile<16x16xi32>
    %136 = constant <i32: 0> : tile<16x16xi32>
    %137 = muli %135, %136 : tile<16x16xi32>
    %138 = addi %132, %137 : tile<16x16xi32>
    %139 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %140 = broadcast %139 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %141 = offset %140, %138 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %142, %143 = load_ptr_tko weak %141 token=%117 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %144, %145 = load_view_tko weak %123[%1, %5] token=%143 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %146 = mulf %144, %142 rounding<nearest_even> : tile<16x16xf64>
    %147 = addf %119, %146 rounding<nearest_even> : tile<16x16xf64>
    %148 = constant <i32: 38> : tile<i32>
    %149 = offset %arg0, %148 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %150 = make_tensor_view %149, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %151 = make_partition_view %150 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %152 = constant <i32: 5> : tile<i32>
    %153 = reshape %152 : tile<i32> -> tile<1x1xi32>
    %154 = broadcast %153 : tile<1x1xi32> -> tile<16x16xi32>
    %155 = iota : tile<16xi32>
    %156 = reshape %155 : tile<16xi32> -> tile<16x1xi32>
    %157 = broadcast %156 : tile<16x1xi32> -> tile<16x16xi32>
    %158 = constant <i32: 0> : tile<16x16xi32>
    %159 = muli %157, %158 : tile<16x16xi32>
    %160 = addi %154, %159 : tile<16x16xi32>
    %161 = iota : tile<16xi32>
    %162 = reshape %161 : tile<16xi32> -> tile<1x16xi32>
    %163 = broadcast %162 : tile<1x16xi32> -> tile<16x16xi32>
    %164 = constant <i32: 0> : tile<16x16xi32>
    %165 = muli %163, %164 : tile<16x16xi32>
    %166 = addi %160, %165 : tile<16x16xi32>
    %167 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %168 = broadcast %167 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %169 = offset %168, %166 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %170, %171 = load_ptr_tko weak %169 token=%145 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %172, %173 = load_view_tko weak %151[%1, %5] token=%171 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %174 = mulf %172, %170 rounding<nearest_even> : tile<16x16xf64>
    %175 = addf %147, %174 rounding<nearest_even> : tile<16x16xf64>
    %176 = constant <i32: 72> : tile<i32>
    %177 = offset %arg0, %176 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %178 = make_tensor_view %177, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %179 = make_partition_view %178 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %180 = constant <i32: 6> : tile<i32>
    %181 = reshape %180 : tile<i32> -> tile<1x1xi32>
    %182 = broadcast %181 : tile<1x1xi32> -> tile<16x16xi32>
    %183 = iota : tile<16xi32>
    %184 = reshape %183 : tile<16xi32> -> tile<16x1xi32>
    %185 = broadcast %184 : tile<16x1xi32> -> tile<16x16xi32>
    %186 = constant <i32: 0> : tile<16x16xi32>
    %187 = muli %185, %186 : tile<16x16xi32>
    %188 = addi %182, %187 : tile<16x16xi32>
    %189 = iota : tile<16xi32>
    %190 = reshape %189 : tile<16xi32> -> tile<1x16xi32>
    %191 = broadcast %190 : tile<1x16xi32> -> tile<16x16xi32>
    %192 = constant <i32: 0> : tile<16x16xi32>
    %193 = muli %191, %192 : tile<16x16xi32>
    %194 = addi %188, %193 : tile<16x16xi32>
    %195 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %196 = broadcast %195 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %197 = offset %196, %194 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %198, %199 = load_ptr_tko weak %197 token=%173 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %200, %201 = load_view_tko weak %179[%1, %5] token=%199 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %202 = mulf %200, %198 rounding<nearest_even> : tile<16x16xf64>
    %203 = addf %175, %202 rounding<nearest_even> : tile<16x16xf64>
    %204 = constant <i32: 73> : tile<i32>
    %205 = offset %arg0, %204 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %206 = make_tensor_view %205, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %207 = make_partition_view %206 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %208 = constant <i32: 7> : tile<i32>
    %209 = reshape %208 : tile<i32> -> tile<1x1xi32>
    %210 = broadcast %209 : tile<1x1xi32> -> tile<16x16xi32>
    %211 = iota : tile<16xi32>
    %212 = reshape %211 : tile<16xi32> -> tile<16x1xi32>
    %213 = broadcast %212 : tile<16x1xi32> -> tile<16x16xi32>
    %214 = constant <i32: 0> : tile<16x16xi32>
    %215 = muli %213, %214 : tile<16x16xi32>
    %216 = addi %210, %215 : tile<16x16xi32>
    %217 = iota : tile<16xi32>
    %218 = reshape %217 : tile<16xi32> -> tile<1x16xi32>
    %219 = broadcast %218 : tile<1x16xi32> -> tile<16x16xi32>
    %220 = constant <i32: 0> : tile<16x16xi32>
    %221 = muli %219, %220 : tile<16x16xi32>
    %222 = addi %216, %221 : tile<16x16xi32>
    %223 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %224 = broadcast %223 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %225 = offset %224, %222 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %226, %227 = load_ptr_tko weak %225 token=%201 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %228, %229 = load_view_tko weak %207[%1, %5] token=%227 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %230 = mulf %228, %226 rounding<nearest_even> : tile<16x16xf64>
    %231 = addf %203, %230 rounding<nearest_even> : tile<16x16xf64>
    %232 = constant <i32: 74> : tile<i32>
    %233 = offset %arg0, %232 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %234 = make_tensor_view %233, shape = [38, 34], strides = [36, 1] : tensor_view<38x34xf64, strides=[36, 1]>
    %235 = make_partition_view %234 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>
    %236 = constant <i32: 8> : tile<i32>
    %237 = reshape %236 : tile<i32> -> tile<1x1xi32>
    %238 = broadcast %237 : tile<1x1xi32> -> tile<16x16xi32>
    %239 = iota : tile<16xi32>
    %240 = reshape %239 : tile<16xi32> -> tile<16x1xi32>
    %241 = broadcast %240 : tile<16x1xi32> -> tile<16x16xi32>
    %242 = constant <i32: 0> : tile<16x16xi32>
    %243 = muli %241, %242 : tile<16x16xi32>
    %244 = addi %238, %243 : tile<16x16xi32>
    %245 = iota : tile<16xi32>
    %246 = reshape %245 : tile<16xi32> -> tile<1x16xi32>
    %247 = broadcast %246 : tile<1x16xi32> -> tile<16x16xi32>
    %248 = constant <i32: 0> : tile<16x16xi32>
    %249 = muli %247, %248 : tile<16x16xi32>
    %250 = addi %244, %249 : tile<16x16xi32>
    %251 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %252 = broadcast %251 : tile<1x1xptr<f64>> -> tile<16x16xptr<f64>>
    %253 = offset %252, %250 : tile<16x16xptr<f64>>, tile<16x16xi32> -> tile<16x16xptr<f64>>
    %254, %255 = load_ptr_tko weak %253 token=%229 : tile<16x16xptr<f64>> -> tile<16x16xf64>, token
    %256, %257 = load_view_tko weak %235[%1, %5] token=%255 : partition_view<tile=(16x16), padding_value = zero, tensor_view<38x34xf64, strides=[36, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<16x16xf64>, token
    %258 = mulf %256, %254 rounding<nearest_even> : tile<16x16xf64>
    %259 = addf %231, %258 rounding<nearest_even> : tile<16x16xf64>
    %260 = constant <i32: 0> : tile<i32>
    %261 = offset %arg2, %260 : tile<ptr<f64>>, tile<i32> -> tile<ptr<f64>>
    %262 = make_tensor_view %261, shape = [38, 34], strides = [34, 1] : tensor_view<38x34xf64, strides=[34, 1]>
    %263 = make_partition_view %262 : partition_view<tile=(16x16), tensor_view<38x34xf64, strides=[34, 1]>, dim_map=[0, 1]>
    %264 = store_view_tko weak %259, %263[%1, %5] token=%257 : tile<16x16xf64>, partition_view<tile=(16x16), tensor_view<38x34xf64, strides=[34, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
