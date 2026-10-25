cuda_tile.module @m {
  entry @read_layout_g3(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>, %arg3: tile<ptr<f32>>, %arg4: tile<f32>, %arg5: tile<i32>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg1 : tile<ptr<f32>>
    %2 = make_tensor_view %1, shape = [4, %arg5, 4], strides = [68, 4, 1] : tile<i32> -> tensor_view<4x?x4xf32, strides=[68, 4, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]>
    %4 = assume div_by<16>, %arg2 : tile<ptr<f32>>
    %5 = make_tensor_view %4, shape = [4, %arg5, 4], strides = [68, 4, 1] : tile<i32> -> tensor_view<4x?x4xf32, strides=[68, 4, 1]>
    %6 = make_partition_view %5 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]>
    %7 = assume div_by<16>, %arg0 : tile<ptr<f32>>
    %8 = make_tensor_view %7, shape = [12, 2, 4], strides = [8, 4, 1] : tensor_view<12x2x4xf32, strides=[8, 4, 1]>
    %9 = make_partition_view %8 : partition_view<tile=(1x1x4), padding_value = zero, tensor_view<12x2x4xf32, strides=[8, 4, 1]>, dim_map=[0, 1, 2]>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14, %15 = get_tile_block_id : tile<i32>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19, %20 = load_view_tko weak %9[%12, %13, %17] token=%0 : partition_view<tile=(1x1x4), padding_value = zero, tensor_view<12x2x4xf32, strides=[8, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x1x4xf32>, token
    %21 = reshape %19 : tile<1x1x4xf32> -> tile<1x4xf32>
    %22 = constant <i32: 0> : tile<i32>
    %23, %24, %25 = get_index_space_shape %3 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]> -> tile<i32>
    %26 = constant <i32: 1> : tile<i32>
    %27 = for %28 in (%22 to %24, step %26) : tile<i32> iter_values(%29 = %21) -> (tile<1x4xf32>) {
      %30 = constant <i32: 3> : tile<i32>
      %31 = divi %12, %30 signed : tile<i32>
      %32, %33 = load_view_tko weak %3[%31, %28, %17] token=%0 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x4x4xf32>, token
      %34 = reshape %32 : tile<1x4x4xf32> -> tile<4x4xf32>
      %35 = constant <i32: 3> : tile<i32>
      %36 = divi %12, %35 signed : tile<i32>
      %37, %38 = load_view_tko weak %6[%36, %28, %17] token=%0 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x4x4xf32>, token
      %39 = reshape %37 : tile<1x4x4xf32> -> tile<4x4xf32>
      %40 = constant <f32: 2.0> : tile<4x4xf32>
      %41 = mulf %39, %40 rounding<nearest_even> : tile<4x4xf32>
      %42 = addf %34, %41 rounding<nearest_even> : tile<4x4xf32>
      %43 = reduce %42 dim=0 identities=[0.0 : f32] : tile<4x4xf32> -> tile<4xf32> (%44: tile<f32>, %45: tile<f32>) {
        %46 = addf %44, %45 rounding<nearest_even> : tile<f32>
        yield %46 : tile<f32>
      }
      %47 = reshape %43 : tile<4xf32> -> tile<1x4xf32>
      %48 = addf %29, %47 rounding<nearest_even> : tile<1x4xf32>
      continue %48 : tile<1x4xf32>
    }
    %49 = reshape %arg4 : tile<f32> -> tile<1x1xf32>
    %50 = broadcast %49 : tile<1x1xf32> -> tile<1x4xf32>
    %51 = mulf %27, %50 rounding<nearest_even> : tile<1x4xf32>
    %52 = reshape %51 : tile<1x4xf32> -> tile<1x1x4xf32>
    %53 = assume div_by<16>, %arg3 : tile<ptr<f32>>
    %54 = make_tensor_view %53, shape = [12, 2, 4], strides = [8, 4, 1] : tensor_view<12x2x4xf32, strides=[8, 4, 1]>
    %55 = make_partition_view %54 : partition_view<tile=(1x1x4), padding_value = zero, tensor_view<12x2x4xf32, strides=[8, 4, 1]>, dim_map=[0, 1, 2]>
    %56 = store_view_tko weak %52, %55[%12, %13, %17] token=%0 : tile<1x1x4xf32>, partition_view<tile=(1x1x4), padding_value = zero, tensor_view<12x2x4xf32, strides=[8, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
