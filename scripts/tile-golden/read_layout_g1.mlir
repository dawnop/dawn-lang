cuda_tile.module @m {
  entry @read_layout_g1(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>, %arg3: tile<ptr<f32>>, %arg4: tile<f32>, %arg5: tile<i32>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg1 : tile<ptr<f32>>
    %2 = make_tensor_view %1, shape = [4, %arg5, 4], strides = [68, 4, 1] : tile<i32> -> tensor_view<4x?x4xf32, strides=[68, 4, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]>
    %4 = assume div_by<16>, %arg2 : tile<ptr<f32>>
    %5 = make_tensor_view %4, shape = [4, %arg5, 4], strides = [68, 4, 1] : tile<i32> -> tensor_view<4x?x4xf32, strides=[68, 4, 1]>
    %6 = make_partition_view %5 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]>
    %7 = assume div_by<16>, %arg0 : tile<ptr<f32>>
    %8 = make_tensor_view %7, shape = [4, 2, 4], strides = [8, 4, 1] : tensor_view<4x2x4xf32, strides=[8, 4, 1]>
    %9 = make_partition_view %8 : partition_view<tile=(1x1x4), padding_value = zero, tensor_view<4x2x4xf32, strides=[8, 4, 1]>, dim_map=[0, 1, 2]>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14, %15 = get_tile_block_id : tile<i32>
    %16, %17, %18 = get_tile_block_id : tile<i32>
    %19, %20 = load_view_tko weak %9[%12, %13, %17] token=%0 : partition_view<tile=(1x1x4), padding_value = zero, tensor_view<4x2x4xf32, strides=[8, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x1x4xf32>, token
    %21 = reshape %19 : tile<1x1x4xf32> -> tile<1x4xf32>
    %22 = constant <i32: 0> : tile<i32>
    %23, %24, %25 = get_index_space_shape %3 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]> -> tile<i32>
    %26 = constant <i32: 1> : tile<i32>
    %27 = for %28 in (%22 to %24, step %26) : tile<i32> iter_values(%29 = %21) -> (tile<1x4xf32>) {
      %30, %31 = load_view_tko weak %3[%12, %28, %17] token=%0 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x4x4xf32>, token
      %32 = reshape %30 : tile<1x4x4xf32> -> tile<4x4xf32>
      %33, %34 = load_view_tko weak %6[%12, %28, %17] token=%0 : partition_view<tile=(1x4x4), padding_value = zero, tensor_view<4x?x4xf32, strides=[68, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x4x4xf32>, token
      %35 = reshape %33 : tile<1x4x4xf32> -> tile<4x4xf32>
      %36 = constant <f32: 2.0> : tile<4x4xf32>
      %37 = mulf %35, %36 rounding<nearest_even> : tile<4x4xf32>
      %38 = addf %32, %37 rounding<nearest_even> : tile<4x4xf32>
      %39 = reduce %38 dim=0 identities=[0.0 : f32] : tile<4x4xf32> -> tile<4xf32> (%40: tile<f32>, %41: tile<f32>) {
        %42 = addf %40, %41 rounding<nearest_even> : tile<f32>
        yield %42 : tile<f32>
      }
      %43 = reshape %39 : tile<4xf32> -> tile<1x4xf32>
      %44 = addf %29, %43 rounding<nearest_even> : tile<1x4xf32>
      continue %44 : tile<1x4xf32>
    }
    %45 = reshape %arg4 : tile<f32> -> tile<1x1xf32>
    %46 = broadcast %45 : tile<1x1xf32> -> tile<1x4xf32>
    %47 = mulf %27, %46 rounding<nearest_even> : tile<1x4xf32>
    %48 = reshape %47 : tile<1x4xf32> -> tile<1x1x4xf32>
    %49 = assume div_by<16>, %arg3 : tile<ptr<f32>>
    %50 = make_tensor_view %49, shape = [4, 2, 4], strides = [8, 4, 1] : tensor_view<4x2x4xf32, strides=[8, 4, 1]>
    %51 = make_partition_view %50 : partition_view<tile=(1x1x4), padding_value = zero, tensor_view<4x2x4xf32, strides=[8, 4, 1]>, dim_map=[0, 1, 2]>
    %52 = store_view_tko weak %48, %51[%12, %13, %17] token=%0 : tile<1x1x4xf32>, partition_view<tile=(1x1x4), padding_value = zero, tensor_view<4x2x4xf32, strides=[8, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
