cuda_tile.module @m {
  entry @entry6_dynamic(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>, %arg3: tile<ptr<f32>>, %arg4: tile<f32>, %arg5: tile<i32>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<f32>>
    %3 = offset %2, %1 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %4 = make_tensor_view %3, shape = [4, %arg5], strides = [32, 1] : tile<i32> -> tensor_view<4x?xf32, strides=[32, 1]>
    %5 = make_partition_view %4 : partition_view<tile=(2x8), padding_value = zero, tensor_view<4x?xf32, strides=[32, 1]>, dim_map=[0, 1]>
    %6 = constant <i32: 0> : tile<i32>
    %7 = assume div_by<16>, %arg1 : tile<ptr<f32>>
    %8 = offset %7, %6 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %9 = make_tensor_view %8, shape = [4, %arg5], strides = [32, 1] : tile<i32> -> tensor_view<4x?xf32, strides=[32, 1]>
    %10 = make_partition_view %9 : partition_view<tile=(2x8), padding_value = zero, tensor_view<4x?xf32, strides=[32, 1]>, dim_map=[0, 1]>
    %11 = constant <i32: 0> : tile<i32>
    %12 = assume div_by<16>, %arg2 : tile<ptr<f32>>
    %13 = offset %12, %11 : tile<ptr<f32>>, tile<i32> -> tile<ptr<f32>>
    %14 = make_tensor_view %13, shape = [4, %arg5], strides = [32, 1] : tile<i32> -> tensor_view<4x?xf32, strides=[32, 1]>
    %15 = make_partition_view %14 : partition_view<tile=(2x8), padding_value = zero, tensor_view<4x?xf32, strides=[32, 1]>, dim_map=[0, 1]>
    %16 = constant <f32: 0.0> : tile<2xf32>
    %17 = constant <i32: 0> : tile<i32>
    %18, %19 = get_index_space_shape %5 : partition_view<tile=(2x8), padding_value = zero, tensor_view<4x?xf32, strides=[32, 1]>, dim_map=[0, 1]> -> tile<i32>
    %20 = constant <i32: 1> : tile<i32>
    %21 = for %22 in (%17 to %19, step %20) : tile<i32> iter_values(%23 = %16) -> (tile<2xf32>) {
      %24, %25, %26 = get_tile_block_id : tile<i32>
      %27, %28 = load_view_tko weak %5[%24, %22] token=%0 : partition_view<tile=(2x8), padding_value = zero, tensor_view<4x?xf32, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<2x8xf32>, token
      %29, %30 = load_view_tko weak %10[%24, %22] token=%0 : partition_view<tile=(2x8), padding_value = zero, tensor_view<4x?xf32, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<2x8xf32>, token
      %31 = constant <f32: 2.0> : tile<2x8xf32>
      %32 = mulf %29, %31 rounding<nearest_even> : tile<2x8xf32>
      %33 = addf %27, %32 rounding<nearest_even> : tile<2x8xf32>
      %34, %35 = load_view_tko weak %15[%24, %22] token=%0 : partition_view<tile=(2x8), padding_value = zero, tensor_view<4x?xf32, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<2x8xf32>, token
      %36 = constant <f32: 4.0> : tile<2x8xf32>
      %37 = mulf %34, %36 rounding<nearest_even> : tile<2x8xf32>
      %38 = addf %33, %37 rounding<nearest_even> : tile<2x8xf32>
      %39 = reduce %38 dim=1 identities=[0.0 : f32] : tile<2x8xf32> -> tile<2xf32> (%40: tile<f32>, %41: tile<f32>) {
        %42 = addf %40, %41 rounding<nearest_even> : tile<f32>
        yield %42 : tile<f32>
      }
      %43 = addf %23, %39 rounding<nearest_even> : tile<2xf32>
      continue %43 : tile<2xf32>
    }
    %44 = reshape %arg4 : tile<f32> -> tile<1xf32>
    %45 = broadcast %44 : tile<1xf32> -> tile<2xf32>
    %46 = mulf %21, %45 rounding<nearest_even> : tile<2xf32>
    %47 = assume div_by<16>, %arg3 : tile<ptr<f32>>
    %48 = make_tensor_view %47, shape = [4], strides = [1] : tensor_view<4xf32, strides=[1]>
    %49 = make_partition_view %48 : partition_view<tile=(2), padding_value = zero, tensor_view<4xf32, strides=[1]>, dim_map=[0]>
    %50, %51, %52 = get_tile_block_id : tile<i32>
    %53 = store_view_tko weak %46, %49[%50] token=%0 : tile<2xf32>, partition_view<tile=(2), padding_value = zero, tensor_view<4xf32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
