cuda_tile.module @m {
  entry @llama_rope(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2, %3, %4 = get_num_tile_blocks : tile<i32>
    %5 = constant <i32: 64> : tile<i32>
    %6 = muli %3, %5 : tile<i32>
    %7 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %8 = make_tensor_view %7, shape = [%6, 32], strides = [32, 1] : tile<i32> -> tensor_view<?x32xf64, strides=[32, 1]>
    %9 = make_partition_view %8 : partition_view<tile=(64x16), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14 = load_view_tko weak %9[%11, %1] token=%0 : partition_view<tile=(64x16), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x16xf64>, token
    %15 = constant <i32: 1> : tile<i32>
    %16, %17 = load_view_tko weak %9[%11, %15] token=%14 : partition_view<tile=(64x16), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x16xf64>, token
    %18 = constant <i32: 0> : tile<i32>
    %19 = constant <i32: 0> : tile<i32>
    %20 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %21 = make_tensor_view %20, shape = [64, 16], strides = [16, 1] : tensor_view<64x16xf64, strides=[16, 1]>
    %22 = make_partition_view %21 : partition_view<tile=(64x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %23, %24 = load_view_tko weak %22[%18, %19] token=%17 : partition_view<tile=(64x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x16xf64>, token
    %25 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %26 = make_tensor_view %25, shape = [64, 16], strides = [16, 1] : tensor_view<64x16xf64, strides=[16, 1]>
    %27 = make_partition_view %26 : partition_view<tile=(64x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>
    %28, %29 = load_view_tko weak %27[%18, %19] token=%24 : partition_view<tile=(64x16), padding_value = zero, tensor_view<64x16xf64, strides=[16, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<64x16xf64>, token
    %30 = mulf %13, %23 rounding<nearest_even> : tile<64x16xf64>
    %31 = mulf %16, %28 rounding<nearest_even> : tile<64x16xf64>
    %32 = subf %30, %31 rounding<nearest_even> : tile<64x16xf64>
    %33 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %34 = make_tensor_view %33, shape = [%6, 32], strides = [32, 1] : tile<i32> -> tensor_view<?x32xf64, strides=[32, 1]>
    %35 = make_partition_view %34 : partition_view<tile=(64x16), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %36, %37, %38 = get_tile_block_id : tile<i32>
    %39 = constant <i32: 2> : tile<i32>
    %40 = muli %36, %39 : tile<i32>
    %41 = store_view_tko weak %32, %35[%11, %40] token=%29 : tile<64x16xf64>, partition_view<tile=(64x16), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %42 = mulf %13, %28 rounding<nearest_even> : tile<64x16xf64>
    %43 = mulf %16, %23 rounding<nearest_even> : tile<64x16xf64>
    %44 = addf %42, %43 rounding<nearest_even> : tile<64x16xf64>
    %45 = constant <i32: 2> : tile<i32>
    %46 = muli %36, %45 : tile<i32>
    %47 = constant <i32: 1> : tile<i32>
    %48 = addi %46, %47 : tile<i32>
    %49 = store_view_tko weak %44, %35[%11, %48] token=%41 : tile<64x16xf64>, partition_view<tile=(64x16), padding_value = zero, tensor_view<?x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
