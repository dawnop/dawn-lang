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
    %14, %15 = load_view_tko weak %13[%4] token=%0 : partition_view<tile=(32), padding_value = zero, tensor_view<512xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xi32>, token
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
    %36 = store_view_tko weak %27, %30[%35, %4] token=%0 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %37 = constant <i32: 1> : tile<i32>
    %38 = constant <i32: 31> : tile<i32>
    %39 = andi %37, %38 : tile<i32>
    %40 = reshape %39 : tile<i32> -> tile<1xi32>
    %41 = broadcast %40 : tile<1xi32> -> tile<256xi32>
    %42 = shri %18, %41 signed : tile<256xi32>
    %43 = trunci %42 : tile<256xi32> -> tile<256xi4>
    %44 = pack %43 : tile<256xi4> -> tile<128xi8>
    %45 = unpack %44 : tile<128xi8> -> tile<32xi32>
    %46 = reshape %45 : tile<32xi32> -> tile<1x32xi32>
    %47 = constant <i32: 8> : tile<i32>
    %48 = muli %32, %47 : tile<i32>
    %49 = constant <i32: 1> : tile<i32>
    %50 = addi %48, %49 : tile<i32>
    %51 = store_view_tko weak %46, %30[%50, %4] token=%36 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %52 = constant <i32: 1> : tile<i32>
    %53 = constant <i32: 31> : tile<i32>
    %54 = andi %52, %53 : tile<i32>
    %55 = reshape %54 : tile<i32> -> tile<1xi32>
    %56 = broadcast %55 : tile<1xi32> -> tile<256xi32>
    %57 = shri %20, %56 signed : tile<256xi32>
    %58 = trunci %57 : tile<256xi32> -> tile<256xi4>
    %59 = pack %58 : tile<256xi4> -> tile<128xi8>
    %60 = unpack %59 : tile<128xi8> -> tile<32xi32>
    %61 = reshape %60 : tile<32xi32> -> tile<1x32xi32>
    %62 = constant <i32: 8> : tile<i32>
    %63 = muli %32, %62 : tile<i32>
    %64 = constant <i32: 2> : tile<i32>
    %65 = addi %63, %64 : tile<i32>
    %66 = store_view_tko weak %61, %30[%65, %4] token=%51 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %67 = muli %18, %19 : tile<256xi32>
    %68 = trunci %67 : tile<256xi32> -> tile<256xi4>
    %69 = pack %68 : tile<256xi4> -> tile<128xi8>
    %70 = unpack %69 : tile<128xi8> -> tile<32xi32>
    %71 = reshape %70 : tile<32xi32> -> tile<1x32xi32>
    %72 = constant <i32: 8> : tile<i32>
    %73 = muli %32, %72 : tile<i32>
    %74 = constant <i32: 3> : tile<i32>
    %75 = addi %73, %74 : tile<i32>
    %76 = store_view_tko weak %71, %30[%75, %4] token=%66 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %77 = select %22, %19, %18 : tile<256xi1>, tile<256xi32>
    %78 = trunci %77 : tile<256xi32> -> tile<256xi4>
    %79 = pack %78 : tile<256xi4> -> tile<128xi8>
    %80 = unpack %79 : tile<128xi8> -> tile<32xi32>
    %81 = reshape %80 : tile<32xi32> -> tile<1x32xi32>
    %82 = constant <i32: 8> : tile<i32>
    %83 = muli %32, %82 : tile<i32>
    %84 = constant <i32: 4> : tile<i32>
    %85 = addi %83, %84 : tile<i32>
    %86 = store_view_tko weak %81, %30[%85, %4] token=%76 : tile<1x32xi32>, partition_view<tile=(1x32), padding_value = zero, tensor_view<5x512xi32, strides=[512, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
