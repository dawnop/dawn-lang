cuda_tile.module @m {
  entry @bitwise_mask(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %9 = trunci %7 : tile<128xi32> -> tile<128xi1>
    %10 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %11 = make_tensor_view %10, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %12 = make_partition_view %11 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %13, %14 = load_view_tko weak %12[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %15 = trunci %13 : tile<128xi32> -> tile<128xi1>
    %16 = constant <i1: 0> : tile<128xi1>
    %17 = select %9, %15, %16 : tile<128xi1>, tile<128xi1>
    %18 = exti %17 unsigned : tile<128xi1> -> tile<128xi32>
    %19 = reshape %18 : tile<128xi32> -> tile<1x128xi32>
    %20 = assume div_by<16>, %arg2 : tile<ptr<i32>>
    %21 = make_tensor_view %20, shape = [4, 512], strides = [512, 1] : tensor_view<4x512xi32, strides=[512, 1]>
    %22 = make_partition_view %21 : partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi32, strides=[512, 1]>, dim_map=[0, 1]>
    %23, %24, %25 = get_tile_block_id : tile<i32>
    %26 = constant <i32: 4> : tile<i32>
    %27 = muli %24, %26 : tile<i32>
    %28 = store_view_tko weak %19, %22[%27, %4] token=%0 : tile<1x128xi32>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %29 = constant <i1: 1> : tile<128xi1>
    %30 = select %9, %29, %15 : tile<128xi1>, tile<128xi1>
    %31 = exti %30 unsigned : tile<128xi1> -> tile<128xi32>
    %32 = reshape %31 : tile<128xi32> -> tile<1x128xi32>
    %33 = constant <i32: 4> : tile<i32>
    %34 = muli %24, %33 : tile<i32>
    %35 = constant <i32: 1> : tile<i32>
    %36 = addi %34, %35 : tile<i32>
    %37 = store_view_tko weak %32, %22[%36, %4] token=%28 : tile<1x128xi32>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %38 = xori %9, %15 : tile<128xi1>
    %39 = exti %38 unsigned : tile<128xi1> -> tile<128xi32>
    %40 = reshape %39 : tile<128xi32> -> tile<1x128xi32>
    %41 = constant <i32: 4> : tile<i32>
    %42 = muli %24, %41 : tile<i32>
    %43 = constant <i32: 2> : tile<i32>
    %44 = addi %42, %43 : tile<i32>
    %45 = store_view_tko weak %40, %22[%44, %4] token=%37 : tile<1x128xi32>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %46 = constant <i1: 1> : tile<128xi1>
    %47 = xori %9, %46 : tile<128xi1>
    %48 = exti %47 unsigned : tile<128xi1> -> tile<128xi32>
    %49 = reshape %48 : tile<128xi32> -> tile<1x128xi32>
    %50 = constant <i32: 4> : tile<i32>
    %51 = muli %24, %50 : tile<i32>
    %52 = constant <i32: 3> : tile<i32>
    %53 = addi %51, %52 : tile<i32>
    %54 = store_view_tko weak %49, %22[%53, %4] token=%45 : tile<1x128xi32>, partition_view<tile=(1x128), padding_value = zero, tensor_view<4x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
