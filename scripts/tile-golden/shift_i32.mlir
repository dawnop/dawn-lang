cuda_tile.module @m {
  entry @shift_i32(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %10 = make_tensor_view %9, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %14 = constant <i32: 31> : tile<128xi32>
    %15 = andi %12, %14 : tile<128xi32>
    %16 = shli %7, %15 : tile<128xi32>
    %17 = reshape %16 : tile<128xi32> -> tile<1x128xi32>
    %18 = assume div_by<16>, %arg2 : tile<ptr<i32>>
    %19 = make_tensor_view %18, shape = [3, 512], strides = [512, 1] : tensor_view<3x512xi32, strides=[512, 1]>
    %20 = make_partition_view %19 : partition_view<tile=(1x128), padding_value = zero, tensor_view<3x512xi32, strides=[512, 1]>, dim_map=[0, 1]>
    %21, %22, %23 = get_tile_block_id : tile<i32>
    %24 = constant <i32: 4> : tile<i32>
    %25 = muli %22, %24 : tile<i32>
    %26 = store_view_tko weak %17, %20[%25, %4] token=%0 : tile<1x128xi32>, partition_view<tile=(1x128), padding_value = zero, tensor_view<3x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %27 = constant <i32: 31> : tile<128xi32>
    %28 = andi %12, %27 : tile<128xi32>
    %29 = shri %7, %28 signed : tile<128xi32>
    %30 = reshape %29 : tile<128xi32> -> tile<1x128xi32>
    %31 = constant <i32: 4> : tile<i32>
    %32 = muli %22, %31 : tile<i32>
    %33 = constant <i32: 1> : tile<i32>
    %34 = addi %32, %33 : tile<i32>
    %35 = store_view_tko weak %30, %20[%34, %4] token=%26 : tile<1x128xi32>, partition_view<tile=(1x128), padding_value = zero, tensor_view<3x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %36 = constant <i32: 31> : tile<128xi32>
    %37 = andi %12, %36 : tile<128xi32>
    %38 = shri %7, %37 unsigned : tile<128xi32>
    %39 = reshape %38 : tile<128xi32> -> tile<1x128xi32>
    %40 = constant <i32: 4> : tile<i32>
    %41 = muli %22, %40 : tile<i32>
    %42 = constant <i32: 2> : tile<i32>
    %43 = addi %41, %42 : tile<i32>
    %44 = store_view_tko weak %39, %20[%43, %4] token=%35 : tile<1x128xi32>, partition_view<tile=(1x128), padding_value = zero, tensor_view<3x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
