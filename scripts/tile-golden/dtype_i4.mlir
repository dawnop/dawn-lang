cuda_tile.module @m {
  entry @dtype_i4(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %9 = pack %7 : tile<32xi32> -> tile<128xi8>
    %10 = unpack %9 : tile<128xi8> -> tile<256xi4>
    %11 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %12 = make_tensor_view %11, shape = [512], strides = [1] : tensor_view<512xi32, strides=[1]>
    %13 = make_partition_view %12 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>
    %14, %15 = load_view_tko weak %13[%4] token=%8 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
    %16 = pack %14 : tile<32xi32> -> tile<128xi8>
    %17 = unpack %16 : tile<128xi8> -> tile<256xi4>
    %18 = exti %10 signed : tile<256xi4> -> tile<256xi32>
    %19 = exti %17 signed : tile<256xi4> -> tile<256xi32>
    %20 = exti %10 unsigned : tile<256xi4> -> tile<256xi32>
    %21 = iota : tile<256xi32>
    %22 = trunci %21 : tile<256xi32> -> tile<256xi1>
    %23 = addi %18, %19 : tile<256xi32>
    %24 = trunci %23 : tile<256xi32> -> tile<256xi4>
    %25 = pack %24 : tile<256xi4> -> tile<128xi8>
    %26 = unpack %25 : tile<128xi8> -> tile<32xi32>
    %27 = reshape %26 : tile<32xi32> -> tile<1x32xi32>
    %28 = assume div_by<16>, %arg2 : tile<ptr<i32>>
    %29 = make_tensor_view %28, shape = [5, 512], strides = [512, 1] : tensor_view<5x512xi32, strides=[512, 1]>
    %30 = make_partition_view %29 : partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>
    %31, %32, %33 = get_tile_block_id : tile<i32>
    %34 = constant <i32: 8> : tile<i32>
    %35 = muli %32, %34 : tile<i32>
    %36 = store_view_tko weak %27, %30[%35, %4] token=%15 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %37 = constant <i32: 1> : tile<256xi32>
    %38 = shri %18, %37 signed : tile<256xi32>
    %39 = trunci %38 : tile<256xi32> -> tile<256xi4>
    %40 = pack %39 : tile<256xi4> -> tile<128xi8>
    %41 = unpack %40 : tile<128xi8> -> tile<32xi32>
    %42 = reshape %41 : tile<32xi32> -> tile<1x32xi32>
    %43 = constant <i32: 8> : tile<i32>
    %44 = muli %32, %43 : tile<i32>
    %45 = constant <i32: 1> : tile<i32>
    %46 = addi %44, %45 : tile<i32>
    %47 = store_view_tko weak %42, %30[%46, %4] token=%36 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %48 = constant <i32: 1> : tile<256xi32>
    %49 = shri %20, %48 signed : tile<256xi32>
    %50 = trunci %49 : tile<256xi32> -> tile<256xi4>
    %51 = pack %50 : tile<256xi4> -> tile<128xi8>
    %52 = unpack %51 : tile<128xi8> -> tile<32xi32>
    %53 = reshape %52 : tile<32xi32> -> tile<1x32xi32>
    %54 = constant <i32: 8> : tile<i32>
    %55 = muli %32, %54 : tile<i32>
    %56 = constant <i32: 2> : tile<i32>
    %57 = addi %55, %56 : tile<i32>
    %58 = store_view_tko weak %53, %30[%57, %4] token=%47 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %59 = muli %18, %19 : tile<256xi32>
    %60 = trunci %59 : tile<256xi32> -> tile<256xi4>
    %61 = pack %60 : tile<256xi4> -> tile<128xi8>
    %62 = unpack %61 : tile<128xi8> -> tile<32xi32>
    %63 = reshape %62 : tile<32xi32> -> tile<1x32xi32>
    %64 = constant <i32: 8> : tile<i32>
    %65 = muli %32, %64 : tile<i32>
    %66 = constant <i32: 3> : tile<i32>
    %67 = addi %65, %66 : tile<i32>
    %68 = store_view_tko weak %63, %30[%67, %4] token=%58 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %69 = select %22, %19, %18 : tile<256xi1>, tile<256xi32>
    %70 = trunci %69 : tile<256xi32> -> tile<256xi4>
    %71 = pack %70 : tile<256xi4> -> tile<128xi8>
    %72 = unpack %71 : tile<128xi8> -> tile<32xi32>
    %73 = reshape %72 : tile<32xi32> -> tile<1x32xi32>
    %74 = constant <i32: 8> : tile<i32>
    %75 = muli %32, %74 : tile<i32>
    %76 = constant <i32: 4> : tile<i32>
    %77 = addi %75, %76 : tile<i32>
    %78 = store_view_tko weak %73, %30[%77, %4] token=%68 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
